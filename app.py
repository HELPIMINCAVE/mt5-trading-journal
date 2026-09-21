from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, render_template, request
from analytics_engine import AnalyticsEngine
from mt5_ingestion import MT5IngestionHandler
from storage_engine import StorageEngine

app = Flask(__name__)

# Initialize system modules
storage = StorageEngine("journal_database.db")
analytics = AnalyticsEngine(storage)
ingestion = MT5IngestionHandler(storage_engine=storage)


@app.route("/")
def index():
    """Renders the main dashboard page."""
    return render_template("index.html")


@app.route("/api/summary", methods=["GET"])
def get_summary():
    """Returns performance summary analytics as JSON."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    summary_data = analytics.generate_performance_summary(
        start_date=start_date, end_date=end_date
    )
    return jsonify(summary_data)


@app.route("/api/behavioral", methods=["GET"])
def get_behavioral():
    """Returns behavioral and execution integrity metrics as JSON."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    behavioral_data = analytics.compute_behavioral_metrics(
        start_date=start_date, end_date=end_date
    )
    return jsonify(behavioral_data)


@app.route("/api/sync", methods=["POST"])
def sync_mt5():
    """Triggers MT5 deal synchronization on demand."""
    try:
        connected = ingestion.connect()
        if not connected:
            return (
                jsonify(
                    {"status": "error", "message": "Failed to connect to MT5"}
                ),
                500,
            )

        # Default sync range: last 30 days if unspecified
        sync_from = datetime.now(timezone.utc) - timedelta(days=30)
        ingested_count = ingestion.sync_closed_deals(date_from=sync_from)

        return jsonify(
            {
                "status": "success",
                "new_trades_synced": ingested_count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    # Runs strictly locally at http://127.0.0.1:5000
    app.run(host="127.0.0.1", port=5000, debug=True)