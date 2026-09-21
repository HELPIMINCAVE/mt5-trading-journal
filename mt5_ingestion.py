import mt5_mac as mt5
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone

class MT5IngestionHandler:
    def __init__(self, storage_engine, account_id=None, password=None, server=None):
        self.storage_engine = storage_engine
        self.account_id = account_id
        self.password = password
        self.server = server
        self.is_connected = False
    
    def connect(self) -> bool:
        """Establishes session connection with the MT5 client terminal and verifies session state."""
        if self.account_id and self.password and self.server:
            initialized = mt5.initialize(
                login=int(self.account_id),
                password=str(self.password),
                server=str(self.server),
            )
        else:
            initialized = mt5.initialize()
        
        if not initialized:
            err = mt5.last_error()  # type: ignore
            print(f"MT5 Terminal Init Failed: {err}")
            self.is_connected = False
            return False
        
        account_info = mt5.account_info()
        if account_info is None:
            print("Connected to terminal, but unable to retrieve account state.")
            mt5.shutdown()
            self.is_connected = False
            return False
        
        self.is_connected = True
        print(
            f"Successfully connected to MT5 Account #{account_info.login} "
            f"[{account_info.company} - Leverage 1:{account_info.leverage}]"
        )
        return True
    
    def sync_closed_deals(self, date_from: datetime) -> int:
        """Fetches closed deals from MT5 between date_from and current time, groups them by

        position ID, calculates risk metrics, and writes new closed trades to the storage engine.
        Returns the count of new trades successfully ingested.
        """
        if not self.is_connected:
            raise ConnectionError(
                "MT5 terminal is not connected. Call connect() first."
            )
        
        date_to = datetime.now(timezone.utc)
        
        # Convert datetime objects to integer Unix timestamps for MT5 API compatibility
        from_timestamp = int(date_from.timestamp())
        to_timestamp = int(date_to.timestamp())
        
        raw_deals = mt5.history_deals_get(from_timestamp, to_timestamp)
        if raw_deals is None:
            err = mt5.last_error()  # type: ignore
            print(f"Failed to fetch MT5 deal history: {err}")
            return 0
        
        # Group raw deal executions by position_id
        deals_by_position: Dict[int, List[Any]] = {}
        for deal in raw_deals:
            # Skip non-trading deals (balance transfers, credit adjustments, zero position IDs)
            if not deal.symbol or deal.position_id == 0: # type: ignore
                continue
            
            position_id = deal.position_id # type: ignore
            if position_id not in deals_by_position:
                deals_by_position[position_id] = []
            deals_by_position[position_id].append(deal)
        
        ingested_count = 0
        
        for position_id, deals in deals_by_position.items():
            entry_deal = None
            exit_deal = None
            
            for deal in deals:
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    entry_deal = deal
                elif deal.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY):
                    exit_deal = deal
            
            # Skip positions that are still open or lack a matching exit deal
            if entry_deal is None or exit_deal is None:
                continue
            
            # Calculate net realized PnL across all deals in this position (profit + swap + commission)
            net_profit = sum(d.profit + d.swap + d.commission for d in deals)
            order_type = "BUY" if entry_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
            
            trade_data = {
                "mt5_ticket": exit_deal.ticket,
                "symbol": entry_deal.symbol,
                "order_type": order_type,
                "lots": entry_deal.volume,
                "open_time": datetime.fromtimestamp(
                    entry_deal.time, tz=timezone.utc
                ).isoformat(),
                "close_time": datetime.fromtimestamp(
                    exit_deal.time, tz=timezone.utc
                ).isoformat(),
                "open_price": entry_deal.price,
                "close_price": exit_deal.price,
                "net_profit": round(net_profit, 2),
            }
            
            # Query symbol parameters and account equity for risk metrics
            symbol_info = mt5.symbol_info(entry_deal.symbol)
            account_info = mt5.account_info()
            account_equity = account_info.equity if account_info else 0.0
            
            # Extract SL and TP from entry or exit records
            sl_price = (
                entry_deal.sl
                if entry_deal.sl > 0
                else (exit_deal.sl if exit_deal.sl > 0 else None)
            )
            tp_price = (
                entry_deal.tp
                if entry_deal.tp > 0
                else (exit_deal.tp if exit_deal.tp > 0 else None)
            )
            
            monetary_risk = self._compute_monetary_risk(
                open_price=entry_deal.price,
                sl_price=sl_price,
                lots=entry_deal.volume,
                symbol_info=symbol_info,
            )
            
            planned_rr = self._compute_planned_rr(
                open_price=entry_deal.price,
                sl_price=sl_price,
                tp_price=tp_price,
            )
            
            realized_r = self._compute_realized_r(
                net_profit=net_profit, monetary_risk=monetary_risk
            )
            
            risk_data = {
                "sl_price": sl_price,
                "tp_price": tp_price,
                "monetary_risk": round(monetary_risk, 2),
                "planned_rr": (
                    round(planned_rr, 2) if planned_rr is not None else None
                ),
                "realized_r": round(realized_r, 2),
                "account_equity": round(account_equity, 2),
            }
            
            try:
                self.storage_engine.insert_trade_record(trade_data, risk_data)
                ingested_count += 1
            except Exception:
                # Storage Engine handles duplicate mt5_ticket constraints gracefully
                pass
        
        return ingested_count
    
    def _compute_monetary_risk(
            self,
            open_price: float,
            sl_price: Optional[float],
            lots: float,
            symbol_info: Any,
    ) -> float:
        """Calculates absolute monetary risk using symbol point size and tick value metrics."""
        if sl_price is None or sl_price == 0 or symbol_info is None:
            return 0.0
        
        point_size = symbol_info.point
        tick_value = symbol_info.trade_tick_value
        
        if point_size == 0 or tick_value == 0:
            return 0.0
        
        point_distance = abs(open_price - sl_price) / point_size
        return point_distance * tick_value * lots
    
    def _compute_planned_rr(
            self, open_price: float, sl_price: Optional[float], tp_price: Optional[float]
    ) -> Optional[float]:
        """Calculates planned Risk-to-Reward ratio."""
        if not sl_price or not tp_price:
            return None
        
        sl_distance = abs(open_price - sl_price)
        tp_distance = abs(tp_price - open_price)
        
        if sl_distance == 0:
            return None
        
        return tp_distance / sl_distance
    
    def _compute_realized_r(
            self, net_profit: float, monetary_risk: float
    ) -> float:
        """Calculates actual realized R-Multiple relative to monetary risk."""
        if monetary_risk <= 0:
            return 0.0
        return net_profit / monetary_risk