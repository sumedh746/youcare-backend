# ------------------------------
# export_and_derive.py
# ------------------------------

import pandas as pd
import psycopg2
from datetime import datetime
import pytz

# -----------------------------------
# 1️⃣ Database connection details
# -----------------------------------
DB_HOST = "localhost"
DB_NAME = "motion_sensor_db"
DB_USER = "postgres"
DB_PASS = "Manutd@107"

# -----------------------------------
# 2️⃣ Connect to PostgreSQL
# -----------------------------------
print("📡 Connecting to database...")
conn = psycopg2.connect(
    host=DB_HOST,
    dbname=DB_NAME,
    user=DB_USER,
    password=DB_PASS
)

# -----------------------------------
# 3️⃣ Fetch raw events from the table
# -----------------------------------
query = """
SELECT 
    id, 
    device_id, 
    name, 
    value AS device_class, 
    state, 
    message, 
    event_time
FROM sensor_events
ORDER BY event_time ASC;
"""

print("📦 Fetching raw events...")
df = pd.read_sql(query, conn)
conn.close()

print(f"✅ Retrieved {len(df)} events from database.")

# -----------------------------------
# 4️⃣ Convert timestamps (UTC → IST)
# -----------------------------------
df['event_time'] = pd.to_datetime(df['event_time'], utc=True)
df['event_time_ist'] = df['event_time'].dt.tz_convert('Asia/Kolkata')

# -----------------------------------
# 5️⃣ Add time breakdown columns
# -----------------------------------
df['day'] = df['event_time_ist'].dt.date
df['hour'] = df['event_time_ist'].dt.hour
df['dow'] = df['event_time_ist'].dt.day_name()

# -----------------------------------
# 6️⃣ Motion and door classification
# -----------------------------------
motion_df = df[df['device_class'] == 'motion']
door_df = df[df['device_class'].isin(['opening', 'door'])]

# -----------------------------------
# 7️⃣ Derived metric 1: Motion count per room/day
# -----------------------------------
motion_counts = (
    motion_df.groupby(['name', 'day'])
    .size()
    .reset_index(name='motion_count')
)

# -----------------------------------
# 8️⃣ Derived metric 2: Door open durations
# -----------------------------------
door_df = door_df.sort_values('event_time')
door_df['next_state'] = door_df['state'].shift(-1)
door_df['next_time'] = door_df['event_time'].shift(-1)

door_open_pairs = door_df[
    (door_df['state'].str.lower().isin(['on', 'open'])) &
    (door_df['next_state'].str.lower().isin(['off', 'closed']))
]

door_open_pairs['duration_s'] = (
    door_open_pairs['next_time'] - door_open_pairs['event_time']
).dt.total_seconds()

door_summary = (
    door_open_pairs.groupby(['name', door_open_pairs['event_time'].dt.date])
    .agg(total_open_s=('duration_s', 'sum'), num_opens=('duration_s', 'count'))
    .reset_index()
    .rename(columns={'event_time': 'day'})
)

# -----------------------------------
# 9️⃣ Merge both summaries
# -----------------------------------
daily_summary = pd.merge(motion_counts, door_summary, on=['name', 'day'], how='outer').fillna(0)

# -----------------------------------
# 🔟 Save both CSVs to motion_backend folder
# -----------------------------------
df.to_csv("/Users/sumedhmore/Desktop/motion_backend/raw_events.csv", index=False)
daily_summary.to_csv("/Users/sumedhmore/Desktop/motion_backend/derived_daily_summary.csv", index=False)
print("💾 Saved raw and derived data to motion_backend folder")

# -----------------------------------
# 1️⃣1️⃣ Show a preview
# -----------------------------------
print("\n📊 Derived Summary:")
print(daily_summary.head())

