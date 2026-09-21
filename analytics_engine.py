from datetime import datetime
from typing import Any, Dict, List, Optional

class AnalyticsEngine:
    """Quantitative analysis engine for calculating performance statistics,

    behavioral metrics, strategy decay, and psychological impacts from trade data.
    """

    def __init__(self, storage_engine: Any):
        self.storage_engine = storage_engine

    def generate_performance_summary(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Calculates core quantitative performance metrics including Win Rate,

        Profit Factor, Mathematical Expectancy, and Max Peak-to-Valley Drawdown.
        """
        raw_dataset = self.storage_engine.fetch_analytics_dataset(
            start_date, end_date
        )

        if not raw_dataset:
            return self._empty_performance_report()

        total_trades = len(raw_dataset)

        # Categorize trades by financial outcome
        winning_trades = [
            t for t in raw_dataset if (t.get("net_profit") or 0) > 0
        ]
        losing_trades = [
            t for t in raw_dataset if (t.get("net_profit") or 0) < 0
        ]

        win_count = len(winning_trades)
        loss_count = len(losing_trades)

        # 1. Win Rate (%)
        win_rate = (win_count / total_trades) * 100.0

        # 2. Profit Factor
        gross_profit = sum(t.get("net_profit", 0.0) for t in winning_trades)
        gross_loss = abs(sum(t.get("net_profit", 0.0) for t in losing_trades))

        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = gross_profit if gross_profit > 0 else 0.0

        # 3. Averages & Mathematical Expectancy
        avg_win = (gross_profit / win_count) if win_count > 0 else 0.0
        avg_loss = (gross_loss / loss_count) if loss_count > 0 else 0.0

        win_prob = win_count / total_trades
        loss_prob = loss_count / total_trades
        expectancy = (win_prob * avg_win) - (loss_prob * avg_loss)

        # 4. Realized R & Peak-to-Valley Drawdown
        valid_r_values = [
            t["realized_r"]
            for t in raw_dataset
            if t.get("realized_r") is not None
        ]
        avg_realized_r = (
            sum(valid_r_values) / len(valid_r_values) if valid_r_values else 0.0
        )
        max_drawdown = self._calculate_max_drawdown(raw_dataset)
        total_net_profit = sum(t.get("net_profit", 0.0) for t in raw_dataset)

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "avg_realized_r": round(avg_realized_r, 2),
            "max_drawdown": round(max_drawdown, 2),
            "total_net_profit": round(total_net_profit, 2),
        }

    def compute_behavioral_metrics(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Evaluates trader execution discipline, calculating Execution Integrity Score

        and tracking financial losses caused by plan violations.
        """
        raw_dataset = self.storage_engine.fetch_analytics_dataset(
            start_date, end_date
        )

        if not raw_dataset:
            return {
                "execution_integrity_score": 0.0,
                "behavioral_cost_index": 0.0,
                "total_violations": 0,
                "error_breakdown": {},
            }

        total_trades = len(raw_dataset)

        # Filter discipline status (1/True = adhered, 0/False = rule violation)
        disciplined_trades = [
            t for t in raw_dataset if bool(t.get("plan_adherence"))
        ]
        violated_trades = [
            t for t in raw_dataset if not bool(t.get("plan_adherence"))
        ]

        # Execution Integrity Score (% of trades executed according to plan)
        integrity_score = (len(disciplined_trades) / total_trades) * 100.0

        # Behavioral Cost Index (Net profit/loss generated solely from violated trades)
        behavioral_cost = sum(
            t.get("net_profit", 0.0) for t in violated_trades
        )

        # Categorize financial impact by specific behavioral error category
        error_breakdown: Dict[str, Dict[str, Any]] = {}
        for trade in violated_trades:
            category = trade.get("error_category") or "Uncategorized Error"
            pnl = trade.get("net_profit", 0.0)

            if category not in error_breakdown:
                error_breakdown[category] = {"count": 0, "total_loss": 0.0}

            error_breakdown[category]["count"] += 1
            error_breakdown[category]["total_loss"] += pnl

        # Round error totals
        for cat in error_breakdown:
            error_breakdown[cat]["total_loss"] = round(
                error_breakdown[cat]["total_loss"], 2
            )

        return {
            "execution_integrity_score": round(integrity_score, 2),
            "behavioral_cost_index": round(behavioral_cost, 2),
            "total_violations": len(violated_trades),
            "error_breakdown": error_breakdown,
        }

    def run_strategy_diagnostics(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Analyzes performance broken down by technical setups. Calculates Strategy Decay

        (the gap between theoretical clean edge and actual execution) to flag failing strategies.
        """
        raw_dataset = self.storage_engine.fetch_analytics_dataset(
            start_date, end_date
        )

        if not raw_dataset:
            return {}

        # Group dataset by setup_tag
        setups: Dict[str, List[Dict[str, Any]]] = {}
        for trade in raw_dataset:
            tag = trade.get("setup_tag") or "Untagged Setup"
            if tag not in setups:
                setups[tag] = []
            setups[tag].append(trade)

        diagnostics: Dict[str, Dict[str, Any]] = {}

        for tag, trades in setups.items():
            clean_trades = [t for t in trades if bool(t.get("plan_adherence"))]

            all_expectancy = self._calculate_expectancy(trades)
            clean_expectancy = self._calculate_expectancy(clean_trades)

            # Strategy Decay = clean edge minus realized edge (positive value indicates human error erosion)
            strategy_decay = clean_expectancy - all_expectancy
            clean_pf = self._calculate_profit_factor(clean_trades)
            sample_size = len(clean_trades)

            # Flag strategy for revision/elimination if sample size >= 30 and edge is negative/unprofitable
            flag_for_elimination = sample_size >= 30 and (
                clean_expectancy < 0 or clean_pf < 1.0
            )

            diagnostics[tag] = {
                "sample_size": sample_size,
                "clean_expectancy": round(clean_expectancy, 2),
                "strategy_decay": round(strategy_decay, 2),
                "profit_factor": round(clean_pf, 2),
                "recommended_action": (
                    "ELIMINATE_OR_REVISE"
                    if flag_for_elimination
                    else "MAINTAIN"
                ),
            }

        return diagnostics

    def analyze_psychological_impact(
        self, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Groups trading metrics by recorded emotional state to identify key psychological leaks."""
        raw_dataset = self.storage_engine.fetch_analytics_dataset(
            start_date, end_date
        )

        if not raw_dataset:
            return {}

        emotions: Dict[str, List[Dict[str, Any]]] = {}
        for trade in raw_dataset:
            state = trade.get("emotional_state") or "Unrecorded"
            if state not in emotions:
                emotions[state] = []
            emotions[state].append(trade)

        psychological_report: Dict[str, Dict[str, Any]] = {}

        for state, trades in emotions.items():
            total_pnl = sum(t.get("net_profit", 0.0) for t in trades)
            r_values = [
                t["realized_r"]
                for t in trades
                if t.get("realized_r") is not None
            ]
            avg_r = sum(r_values) / len(r_values) if r_values else 0.0

            psychological_report[state] = {
                "trade_count": len(trades),
                "total_pnl": round(total_pnl, 2),
                "avg_realized_r": round(avg_r, 2),
            }

        return psychological_report

    # -------------------------------------------------------------------------
    # INTERNAL HELPER METHODS
    # -------------------------------------------------------------------------
    def _calculate_max_drawdown(self, dataset: List[Dict[str, Any]]) -> float:
        """Calculates maximum peak-to-valley monetary drawdown across a chronological sequence of trades."""
        sorted_trades = sorted(dataset, key=lambda x: x.get("close_time", ""))

        cumulative_pnl = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for trade in sorted_trades:
            pnl = trade.get("net_profit", 0.0)
            cumulative_pnl += pnl

            if cumulative_pnl > peak:
                peak = cumulative_pnl

            drawdown = peak - cumulative_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return max_drawdown

    def _calculate_expectancy(self, dataset: List[Dict[str, Any]]) -> float:
        """Calculates mathematical expectation ($ per trade) for a given subset of trades."""
        if not dataset:
            return 0.0

        total_count = len(dataset)
        wins = [t for t in dataset if (t.get("net_profit") or 0) > 0]
        losses = [t for t in dataset if (t.get("net_profit") or 0) < 0]

        win_count = len(wins)
        loss_count = len(losses)

        avg_win = (
            sum(t.get("net_profit", 0.0) for t in wins) / win_count
            if win_count > 0
            else 0.0
        )
        avg_loss = (
            abs(sum(t.get("net_profit", 0.0) for t in losses)) / loss_count
            if loss_count > 0
            else 0.0
        )

        return ((win_count / total_count) * avg_win) - (
            (loss_count / total_count) * avg_loss
        )

    def _calculate_profit_factor(self, dataset: List[Dict[str, Any]]) -> float:
        """Calculates Gross Profit divided by Gross Loss for a given subset of trades."""
        gross_profit = sum(
            t.get("net_profit", 0.0)
            for t in dataset
            if (t.get("net_profit") or 0) > 0
        )
        gross_loss = abs(
            sum(
                t.get("net_profit", 0.0)
                for t in dataset
                if (t.get("net_profit") or 0) < 0
            )
        )

        if gross_loss == 0:
            return gross_profit if gross_profit > 0 else 0.0
        return gross_profit / gross_loss

    def _empty_performance_report(self) -> Dict[str, Any]:
        """Returns zeroed default response for empty queries."""
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_realized_r": 0.0,
            "max_drawdown": 0.0,
            "total_net_profit": 0.0,
        }