import os, re, secrets, pytesseract
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template, request, session
from PIL import Image
from analytics_engine import AnalyticsEngine
from storage_engine import StorageEngine

app = Flask(__name__)
# Cryptographically random key for secure session cookies
app.secret_key = secrets.token_hex(24)

# Tesseract binary path for macOS (Homebrew Apple Silicon)
# Uncomment or adjust for your system if needed:
pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"

storage = StorageEngine("journal_database.db")
analytics = AnalyticsEngine(storage)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def parse_full_history_screenshot(image_path: str) -> dict:
    """Pre-processes MT5 desktop dark-mode screenshots, performing 3x DPI upscaling

    and luminance thresholding to extract open/close times, wins/losses, symbols,
    and net PnL accurately.
    """
    raw_img = Image.open(image_path)

    # 1. Upscale image 3x to raise DPI for small MT5 desktop text
    orig_w, orig_h = raw_img.size
    upscaled_img = raw_img.resize(
        (orig_w * 3, orig_h * 3), Image.Resampling.LANCZOS
    )

    # 2. Convert to Grayscale & apply Luminance Thresholding
    # Converts white/light text (>65 luminance) to pure BLACK (0)
    # and dark grey background (<65 luminance) to pure WHITE (255)
    gray = upscaled_img.convert("L")
    binary_img = gray.point(lambda p: 0 if p > 65 else 255, mode="1")

    # 3. OCR extraction with Page Segmentation Mode 6 (Single uniform text block)
    ocr_text = pytesseract.image_to_string(binary_img, config="--psm 6")

    lines = ocr_text.splitlines()
    parsed_trades = []

    detected_deposit = None
    total_wins = 0
    total_losses = 0
    total_profit = 0.0

    for line in lines:
        # A. Check if line contains an explicit Deposit row
        if re.search(r"\bdeposit\b", line, re.IGNORECASE):
            deposit_nums = re.findall(r"[+-]?\d+\.\d{2}", line)
            if deposit_nums:
                detected_deposit = float(deposit_nums[-1].replace(",", ""))
            continue

        # B. Check for trade execution rows (buy or sell)
        type_match = re.search(r"\b(buy|sell)\b", line, re.IGNORECASE)
        if not type_match:
            continue

        order_type = type_match.group(1).upper()

        # Extract timestamps (e.g., 2026.09.22 09:54:53)
        timestamps = re.findall(
            r"\d{4}[\.-]\d{2}[\.-]\d{2}\s+\d{2}:\d{2}:\d{2}", line
        )
        open_time = timestamps[0] if len(timestamps) > 0 else "N/A"
        close_time = timestamps[1] if len(timestamps) > 1 else open_time

        # Extract symbol (e.g., goldmicro, EURUSD, XAUUSD, BTCUSD)
        symbol_match = re.search(
            r"\b([a-zA-Z0-9\._]{3,12})\b", line, re.IGNORECASE
        )
        symbol = (
            symbol_match.group(1).upper()
            if symbol_match
            else "CUSTOM_SYMBOL"
        )

        # Extract lot size (e.g., 0.1, 0.01, 1.0)
        lot_match = re.search(r"\b(\d+\.\d{1,2})\b", line)
        lots = float(lot_match.group(1)) if lot_match else 0.10

        # Extract net profit (filtering out MT5 desktop return percentages like -0.03%)
        decimal_numbers = re.findall(r"[+-]?\d+\.\d{2}", line)

        if decimal_numbers:
            if "%" in line and len(decimal_numbers) >= 2:
                pnl = float(decimal_numbers[-2].replace(",", ""))
            else:
                pnl = float(decimal_numbers[-1].replace(",", ""))
        else:
            pnl = 0.00

        total_profit += pnl

        if pnl > 0:
            total_wins += 1
        elif pnl < 0:
            total_losses += 1

        trade_idx = len(parsed_trades) + 1
        parsed_trades.append(
            {
                "mt5_ticket": 400000000 + trade_idx,
                "open_time": open_time,
                "close_time": close_time,
                "symbol": symbol,
                "order_type": order_type,
                "lots": lots,
                "net_profit": pnl,
            }
        )

    total_trades = len(parsed_trades)
    if total_trades == 0:
        raise ValueError(
            "No valid MT5 trade rows could be extracted from image."
        )

    # Default starting balance to 0.00 if no deposit row exists in screenshot
    starting_balance = (
        detected_deposit if detected_deposit is not None else 0.00
    )
    current_equity = starting_balance + total_profit

    # Generate points for equity curve chart
    running_eq = starting_balance
    equity_points = [running_eq]
    labels = ["Start"]

    for i, t in enumerate(parsed_trades, start=1):
        running_eq += t["net_profit"]
        equity_points.append(round(running_eq, 2))
        labels.append(f"Trade #{i}")

    win_rate = round((total_wins / total_trades) * 100, 1)

    return {
        "account_id": f"MT5-DESKTOP-{secrets.token_hex(2).upper()}",
        "starting_balance": round(starting_balance, 2),
        "current_equity": round(current_equity, 2),
        "total_profit": round(total_profit, 2),
        "total_trades": total_trades,
        "total_wins": total_wins,
        "total_losses": total_losses,
        "win_rate": win_rate,
        "trades": parsed_trades,
        "equity_curve": {"labels": labels, "data": equity_points},
    }


@app.route("/")
def index():
    return render_template("index.html")


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
        parsed_data = parse_full_history_screenshot(filepath)

        # Store trade records in database engine
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

        # Establish one-time login session
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