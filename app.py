import os
import re
import secrets
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request, session
from PIL import Image
import pytesseract
from analytics_engine import AnalyticsEngine
from storage_engine import StorageEngine

app = Flask(__name__)
app.secret_key = secrets.token_hex(24)

storage = StorageEngine("journal_database.db")
analytics = AnalyticsEngine(storage)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def parse_full_history_screenshot(image_path: str) -> dict:
    """Parses a full MT5 history screenshot extracting initial balance

    and all individual trade rows to calculate total equity evolution.
    """
    img = Image.open(image_path)
    ocr_text = pytesseract.image_to_string(img)

    # 1. Extract Account ID / Broker Info
    account_match = re.search(r"\b\d{6,10}\b", ocr_text)
    account_id = (
        account_match.group(0) if account_match else f"MT5-{secrets.token_hex(3).upper()}"
    )

    # 2. Extract Initial Deposit / Starting Balance
    deposit_match = re.search(
        r"(?:Deposit|Balance)[:\s]+\$?([\d,]+\.\d{2})",
        ocr_text,
        re.IGNORECASE,
    )
    starting_balance = (
        float(deposit_match.group(1).replace(",", ""))
        if deposit_match
        else 1000.00
    )

    # 3. Extract All Trade Lines across full history
    # Matches patterns like: "EURUSD buy 0.10 at 1.0850 ... +45.00" or "GBPUSD sell 0.50 ... -12.50"
    trade_pattern = re.compile(
        r"([A-Z0-9]{6})\s+(buy|sell)\s+([\d\.]+)\s+.*?([+-]?[\d,]+\.\d{2})$",
        re.MULTILINE | re.IGNORECASE,
    )

    raw_trades = trade_pattern.findall(ocr_text)

    parsed_trades = []
    current_equity = starting_balance
    equity_points = [starting_balance]
    labels = ["Deposit"]

    total_wins = 0
    total_losses = 0

    for idx, (symbol, order_type, lots, pnl_str) in enumerate(raw_trades, start=1):
        pnl = float(pnl_str.replace(",", ""))
        current_equity += pnl

        if pnl > 0:
            total_wins += 1
        elif pnl < 0:
            total_losses += 1

        parsed_trades.append(
            {
                "mt5_ticket": 100000 + idx,
                "symbol": symbol.upper(),
                "order_type": order_type.upper(),
                "lots": float(lots),
                "open_time": datetime.now(timezone.utc).isoformat(),
                "close_time": datetime.now(timezone.utc).isoformat(),
                "net_profit": pnl,
            }
        )

        equity_points.append(round(current_equity, 2))
        labels.append(f"Trade #{idx}")

    total_trades = len(parsed_trades)
    win_rate = (
        round((total_wins / total_trades) * 100, 1) if total_trades > 0 else 0.0
    )

    return {
        "account_id": account_id,
        "starting_balance": starting_balance,
        "current_equity": round(current_equity, 2),
        "total_profit": round(current_equity - starting_balance, 2),
        "total_trades": total_trades,
        "win_rate": win_rate,
        "trades": parsed_trades,
        "equity_curve": {"labels": labels, "data": equity_points},
    }


@app.route("/")
def index():
    # If session exists, frontend will load directly into the dashboard
    is_authenticated = "account_id" in session
    return render_template("index.html", authenticated=is_authenticated)


@app.route("/api/login-via-screenshot", methods=["POST"])
def login_via_screenshot():
    if "screenshot" not in request.files:
        return (
            jsonify({"status": "error", "message": "No screenshot provided"}),
            400,
        )

    file = request.files["screenshot"]
    if file.filename == "":
        return (
            jsonify({"status": "error", "message": "Empty file selected"}),
            400,
        )

    filepath = os.path.join(UPLOAD_FOLDER, f"temp_{file.filename}")
    file.save(filepath)

    try:
        # Parse entire trading history from screenshot
        parsed_data = parse_full_history_screenshot(filepath)

        # Store trade records into database
        for trade in parsed_data["trades"]:
            try:
                storage.insert_trade_record(
                    trade,
                    {
                        "sl_price": None,
                        "tp_price": None,
                        "monetary_risk": 0.0,
                        "planned_rr": None,
                        "realized_r": 0.0,
                        "account_equity": parsed_data["current_equity"],
                    },
                )
            except Exception:
                pass

        # Authorize one-time session
        session["account_id"] = parsed_data["account_id"]

        return jsonify({"status": "success", "data": parsed_data})

    except Exception as e:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": f"Failed to parse history: {str(e)}",
                }
            ),
            500,
        )
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"status": "success", "message": "Session terminated"})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)