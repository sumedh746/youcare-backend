import jwt, datetime

# Must match the SECRET_KEY in your app.py
SECRET_KEY = "my_fixed_secret_key_2025"

token = jwt.encode(
    {
        "user_id": 1,
        "email": "sumedhm276@gmail.com",
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=365)
    },
    SECRET_KEY,
    algorithm="HS256"
)

print("✅ New valid token:")
print(token)

