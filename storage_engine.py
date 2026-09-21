import sqlite3
from typing import Any, Dict, List, Optional


class StorageEngine:
    """Manages SQLite database connections, schema migrations, and atomic operational

    transactions for the MT5 trading journal.
    """

    def __init__(self, db_path: str = "trading_journal.db"):
        self.db_path = db_path
        self.connection = sqlite3.connect(self.db_path)

        # Allow dictionary-style column access on returned rows
        self.connection.row_factory = sqlite3.Row

        # Explicitly enable foreign key constraints in SQLite
        self.connection.execute("PRAGMA foreign_keys = ON;")

        # Initialize schema tables on startup
        self.initialize_database()

    def initialize_database(self) -> None:
        """Creates database tables and performance indexes if they do not exist."""
        schema_queries = [
            """
            CREATE TABLE IF NOT EXISTS trades (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                mt5_ticket INTEGER UNIQUE NOT NULL,
                symbol TEXT NOT NULL,
                order_type TEXT NOT NULL,
                lots REAL NOT NULL,
                open_time TEXT NOT NULL,
                close_time TEXT NOT NULL,
                open_price REAL NOT NULL,
                close_price REAL NOT NULL,
                net_profit REAL NOT NULL,
                is_reviewed BOOLEAN DEFAULT 0
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS risk_metrics (
                metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                sl_price REAL,
                tp_price REAL,
                monetary_risk REAL NOT NULL,
                planned_rr REAL,
                realized_r REAL NOT NULL,
                account_equity REAL NOT NULL,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS behavioral_mindset (
                mindset_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL UNIQUE,
                emotional_state TEXT NOT NULL,
                confidence_rating INTEGER CHECK(confidence_rating BETWEEN 1 AND 5),
                plan_adherence BOOLEAN NOT NULL,
                error_category TEXT,
                notes TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id) ON DELETE CASCADE
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS strategy_visuals (
                visual_id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL UNIQUE,
                setup_tag TEXT NOT NULL,
                confluence_tags TEXT,
                img_before_path TEXT,
                img_after_path TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades (trade_id) ON DELETE CASCADE
            );
            """,
            "CREATE INDEX IF NOT EXISTS idx_trades_ticket ON trades(mt5_ticket);",
            "CREATE INDEX IF NOT EXISTS idx_trades_close_time ON trades(close_time);",
        ]

        with self.connection:
            cursor = self.connection.cursor()
            for query in schema_queries:
                cursor.execute(query)

    def insert_trade_record(
        self, trade_data: Dict[str, Any], risk_data: Dict[str, Any]
    ) -> int:
        """Atomically inserts raw MT5 execution details and calculated risk metrics.

        Returns the generated trade_id.
        """
        insert_trade_sql = """
            INSERT INTO trades (
                mt5_ticket, symbol, order_type, lots,
                open_time, close_time, open_price, close_price, net_profit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        insert_risk_sql = """
            INSERT INTO risk_metrics (
                trade_id, sl_price, tp_price, monetary_risk,
                planned_rr, realized_r, account_equity
            ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """

        # Context manager ('with self.connection') automatically opens transaction
        # and issues COMMIT on success or ROLLBACK on exception
        with self.connection:
            cursor = self.connection.cursor()

            cursor.execute(
                insert_trade_sql,
                (
                    trade_data["mt5_ticket"],
                    trade_data["symbol"],
                    trade_data["order_type"],
                    trade_data["lots"],
                    trade_data["open_time"],
                    trade_data["close_time"],
                    trade_data["open_price"],
                    trade_data["close_price"],
                    trade_data["net_profit"],
                ),
            )
            trade_id = cursor.lastrowid

            cursor.execute(
                insert_risk_sql,
                (
                    trade_id,
                    risk_data.get("sl_price"),
                    risk_data.get("tp_price"),
                    risk_data["monetary_risk"],
                    risk_data.get("planned_rr"),
                    risk_data["realized_r"],
                    risk_data["account_equity"],
                ),
            )

            return trade_id

    def update_journal_entry(
        self,
        trade_id: int,
        mindset_data: Dict[str, Any],
        visual_data: Dict[str, Any],
    ) -> None:
        """Upserts qualitative psychology and setup tags, then marks the trade as reviewed."""
        upsert_mindset_sql = """
            INSERT INTO behavioral_mindset (
                trade_id, emotional_state, confidence_rating, plan_adherence, error_category, notes
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                emotional_state=excluded.emotional_state,
                confidence_rating=excluded.confidence_rating,
                plan_adherence=excluded.plan_adherence,
                error_category=excluded.error_category,
                notes=excluded.notes;
        """
        upsert_visuals_sql = """
            INSERT INTO strategy_visuals (
                trade_id, setup_tag, confluence_tags, img_before_path, img_after_path
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(trade_id) DO UPDATE SET
                setup_tag=excluded.setup_tag,
                confluence_tags=excluded.confluence_tags,
                img_before_path=excluded.img_before_path,
                img_after_path=excluded.img_after_path;
        """
        update_flag_sql = (
            "UPDATE trades SET is_reviewed = 1 WHERE trade_id = ?;"
        )

        with self.connection:
            cursor = self.connection.cursor()
            cursor.execute(
                upsert_mindset_sql,
                (
                    trade_id,
                    mindset_data["emotional_state"],
                    mindset_data["confidence_rating"],
                    int(mindset_data["plan_adherence"]),
                    mindset_data.get("error_category"),
                    mindset_data.get("notes"),
                ),
            )
            cursor.execute(
                upsert_visuals_sql,
                (
                    trade_id,
                    visual_data["setup_tag"],
                    visual_data.get("confluence_tags"),
                    visual_data.get("img_before_path"),
                    visual_data.get("img_after_path"),
                ),
            )
            cursor.execute(update_flag_sql, (trade_id,))

    def fetch_unreviewed_trades(self) -> List[Dict[str, Any]]:
        """Queries all trades pending manual journal review."""
        sql = """
            SELECT t.*, r.sl_price, r.tp_price, r.monetary_risk, r.planned_rr, r.realized_r, r.account_equity
            FROM trades t
            JOIN risk_metrics r ON t.trade_id = r.trade_id
            WHERE t.is_reviewed = 0
            ORDER BY t.close_time DESC;
        """
        cursor = self.connection.cursor()
        cursor.execute(sql)
        return [dict(row) for row in cursor.fetchall()]

    def fetch_analytics_dataset(
        self, start_date: str, end_date: str
    ) -> List[Dict[str, Any]]:
        """Queries fully enriched dataset (trade + risk + mindset + strategy) for analytics engine."""
        sql = """
            SELECT
                t.*,
                r.sl_price, r.tp_price, r.monetary_risk, r.planned_rr, r.realized_r, r.account_equity,
                b.emotional_state, b.confidence_rating, b.plan_adherence, b.error_category, b.notes,
                v.setup_tag, v.confluence_tags, v.img_before_path, v.img_after_path
            FROM trades t
            LEFT JOIN risk_metrics r ON t.trade_id = r.trade_id
            LEFT JOIN behavioral_mindset b ON t.trade_id = b.trade_id
            LEFT JOIN strategy_visuals v ON t.trade_id = v.trade_id
            WHERE t.close_time BETWEEN ? AND ?
            ORDER BY t.close_time ASC;
        """
        cursor = self.connection.cursor()
        cursor.execute(sql, (start_date, end_date))
        return [dict(row) for row in cursor.fetchall()]

    def close(self) -> None:
        """Closes active database connection."""
        if self.connection:
            self.connection.close()