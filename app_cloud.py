from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
import bcrypt
import jwt
import datetime
import os
import pytz
import requests


def normalize_device_name(device_id: str) -> str:
    """
    Convert zigbee2mqtt / HA entity id into a clean device name
    """
    if not device_id:
        return "Unknown Sensor"

    # Example: zigbee2mqtt/bedroom_motion
    # or binary_sensor.bedroom_motion_sensor_occupancy
    name = device_id.split("/")[-1].split(".")[-1]

    name = (
        name.replace("_occupancy", "")
            .replace("_contact", "")
            .replace("_sensor", "")
            .replace("_binary", "")
            .replace("_", " ")
            .strip()
            .title()
    )

    return name


# ============================================================
# 🚀 Flask Setup
# ============================================================

app = Flask(__name__)
CORS(app)

SECRET_KEY = os.getenv("SECRET_KEY", "my_fixed_secret_key_2025")

BREVO_API_KEY = os.getenv("BREVO_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_FROM_NAME = os.getenv("EMAIL_FROM_NAME")


# ============================================================
# 🗄️ PostgreSQL Settings
# ============================================================

def get_db_connection():
    try:
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise Exception("DATABASE_URL not set")

        return psycopg2.connect(database_url, sslmode="require")

    except Exception as e:
        print("❌ DB Connection Error:", e)
        return None


# ============================================================
# 🏠 Default Route
# ============================================================

@app.route("/")
def home():
    return jsonify({"message": "Flask backend running with Zigbee2MQTT!"}), 200
    
    

# ============================================================
# 🧠 Alert Deduplication Cache (in-memory)
# ============================================================

ALERT_COOLDOWNS = {
    "inactivity": 30 * 60,
    "door": 15 * 60,
    "bathroom": 12 * 60,
    "sos": 0,       # 🚨 NEVER suppress emergency
    "panic": 0     # safety alias
}

last_alert_sent = {}
latest_battery = {}




# ============================================================
# 🧑‍💻 User Signup
# ============================================================

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    full_name = data.get("full_name")
    email = data.get("email")
    password = data.get("password")

    if not all([full_name, email, password]):
        return jsonify({"error": "Missing required fields"}), 400

    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500

    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"error": "Email already exists"}), 400

    cur.execute(
        "INSERT INTO users (full_name, email, password_hash) VALUES (%s, %s, %s)",
        (full_name, email, hashed_pw.decode())
    )
    conn.commit()
    cur.close()
    conn.close()

    print(f"✅ Registered new user: {email}")
    return jsonify({"message": "Signup successful"}), 201


# ============================================================
# 🔐 Login (Hardcoded Credentials)
# ============================================================

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    # 🔐 Only one allowed user
    if email == "sumedhm276@gmail.com" and password == "Realmadrid@107":
        token = jwt.encode(
            {
                "user_id": 1,
                "email": email,
                "exp": datetime.datetime.utcnow() + datetime.timedelta(days=365)
            },
            SECRET_KEY,
            algorithm="HS256"
        )

        return jsonify({
            "token": token,
            "full_name": "Sumedh More"
        }), 200

    return jsonify({"error": "Invalid Username or Password"}), 401


# ============================================================
# 📥 POST /events → Called by bridge.py (Zigbee2MQTT Events)
# ============================================================

@app.route("/events", methods=["POST"])
def add_event():
    # Must include JWT token
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    # Validate token
    try:
        decoded = jwt.decode(token.split(" ")[1], SECRET_KEY, algorithms=["HS256"])
        user_id = decoded["user_id"]
    except Exception as e:
        print("❌ JWT Error:", e)
        return jsonify({"error": "Invalid or expired token"}), 403

    data = request.json or {}

    device_id = data.get("device_id")
    state = data.get("state")
    value = data.get("value")
    message = data.get("message")

    # ✅ SINGLE validation
    if not all([device_id, state, value]):
        return jsonify({"error": "Missing event fields"}), 400

    # ✅ Normalize name ONCE
    name = normalize_device_name(device_id)

    # ✅ Single timestamp
    event_time = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)

    print(f"🟢 Event received → {name} | {value} | {state}")

    # Save to DB
    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "DB connection failed"}), 500

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO sensor_events
        (device_id, user_id, name, state, value, message, event_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (device_id, user_id, name, state, value, message, event_time)
    )

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Event added"}), 201


# ============================================================
# 📤 GET /events → Used by iOS app to fetch stored events
# ============================================================

@app.route("/events", methods=["GET"])
def get_events():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    try:
        decoded = jwt.decode(token.split(" ")[1], SECRET_KEY, algorithms=["HS256"])
        user_id = decoded["user_id"]
    except:
        return jsonify({"error": "Invalid token"}), 403

    conn = get_db_connection()
    if conn is None:
        return jsonify({"error": "DB connection failed"}), 500

    cur = conn.cursor()
    cur.execute("""
        SELECT device_id, name, state, value, message, event_time
        FROM sensor_events
        WHERE user_id=%s
        ORDER BY event_time DESC
        LIMIT 100
    """, (user_id,))
    rows = cur.fetchall()

    events = []
    for device_id, name, state, value, message, event_time in rows:
        # Format timestamp cleanly
        if event_time is not None:
            if event_time.tzinfo is None:
                event_time = pytz.timezone("Asia/Kolkata").localize(event_time)
            formatted_time = event_time.isoformat()
        else:
            formatted_time = ""

        events.append({
            "entity_id": device_id,
            "name": name,
            "state": state,
            "message": message,
            "value": value,
            "when": formatted_time
        })

    cur.close()
    conn.close()

    return jsonify(events), 200
    

# ============================================================
# 🔋 POST /battery → Live battery updates from Zigbee2MQTT
# ============================================================

@app.route("/battery", methods=["POST"])
def battery_update():
    data = request.json
    device = data.get("device")
    battery = data.get("battery")

    if device is None or battery is None:
        return jsonify({"error": "Missing device or battery"}), 400

    latest_battery[device] = battery
    print(f"🔋 Battery update → {device}: {battery}%")

    return jsonify({"ok": True}), 200

@app.route("/battery", methods=["GET"])
def get_battery():
    return jsonify(latest_battery), 200

    
def send_email(to_email, subject, body):
    try:
        url = "https://api.brevo.com/v3/smtp/email"

        payload = {
            "sender": {
                "email": EMAIL_FROM,
                "name": EMAIL_FROM_NAME
            },
            "to": [
                {"email": to_email}
            ],
            "subject": subject,
            "htmlContent": f"<html><body><p>{body}</p></body></html>"
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY
        }

        response = requests.post(url, json=payload, headers=headers)

        if response.status_code in (200, 201):
            print(f"📧 Brevo email sent to {to_email}")
            return True
        else:
            print("❌ Brevo error:", response.status_code, response.text)
            return False

    except Exception as e:
        print("❌ Email exception:", e)
        return False



def should_send_alert(user_id, alert_type):
    now = datetime.datetime.utcnow()

    key = f"{user_id}:{alert_type}"
    cooldown = ALERT_COOLDOWNS.get(alert_type, 0)

    last_time = last_alert_sent.get(key)
    if last_time:
        elapsed = (now - last_time).total_seconds()
        if elapsed < cooldown:
            print(f"⛔ Skipping duplicate {alert_type} alert ({int(elapsed)}s since last)")
            return False

    last_alert_sent[key] = now
    return True

# ============================================================
# 📣 POST /alert → Send emails to caregiver group
# ============================================================

@app.route("/alert", methods=["POST"])
def send_alert():
    token = request.headers.get("Authorization")
    if not token:
        return jsonify({"error": "Missing token"}), 401

    try:
        decoded = jwt.decode(token.split(" ")[1], SECRET_KEY, algorithms=["HS256"])
        user_id = decoded["user_id"]
    except Exception as e:
        print("❌ JWT Error:", e)
        return jsonify({"error": "Invalid token"}), 403

    data = request.json
    alert_type = data.get("type")
    alert_type = alert_type.lower()
    recipients = data.get("recipients", [])
    metadata = data.get("metadata", {})

    if not recipients or not isinstance(recipients, list):
        return jsonify({"error": "Recipients list required"}), 400

    # --------------------------------------------------
    # 🧠 DEDUP CHECK (THE FIX)
    # --------------------------------------------------
    if not should_send_alert(user_id, alert_type):
        return jsonify({
            "message": "Duplicate alert suppressed"
        }), 200

    # --------------------------------------------------
    # 📧 Build email (FIXED)
    # --------------------------------------------------
    now_str = datetime.datetime.now(
        pytz.timezone("Asia/Kolkata")
    ).strftime("%I:%M %p")
    
    if alert_type in ("sos", "panic"):
        subject = f"🚨 EMERGENCY SOS ALERT ({now_str})"
        body = ( "🚨 PANIC BUTTON PRESSED\n\n"
        "Immediate assistance is required.\n\n"
        "Please check on the user immediately."
    )

    elif alert_type == "inactivity":
        subject = f"🚨 Inactivity Alert ({now_str})"
        body = f"No motion detected for {metadata.get('minutes', 0)} minutes."

    elif alert_type == "door":
        subject = f"🚪 Door Left Open Alert ({now_str})"
        body = f"Door has been open for {metadata.get('minutes', 0)} minutes."

    elif alert_type == "bathroom":
        subject = f"🚽 Bathroom Activity Alert ({now_str})"
        body = (
            f"Bathroom visits today: {metadata.get('count', 0)}\n"
            f"Threshold: {metadata.get('threshold', 0)}"
        )

    else:
        subject = f"🚨 YouCare Alert ({now_str})"
        body = "YouCare Alert"

    sent = 0
    for email in recipients:
        if send_email(email, subject, body):
            sent += 1

    print(f"📧 Emails sent: {sent}/{len(recipients)}")

    return jsonify({
        "message": "Alert sent",
        "sent": sent,
        "total": len(recipients)
    }), 200

# ============================================================
# 🚀 Start Server
# ============================================================

if __name__ == "__main__":
    print("🚀 Flask backend running on http://127.0.0.1:5001")
    app.run(host="0.0.0.0", port=5001)

