"""
collector_multi_db.py

- Collects weather + AQI for multiple cities
- Stores readings into SQLite (microclimate.db)
- Automatic table creation / migration
- Robust retry logic and coord-based AQI fallback
- Logging for production readiness
"""

import os
import time
import random
import logging
import sqlite3
import requests
from datetime import datetime, timezone
from typing import Optional, Dict

# ---------------------------
# CONFIG
# ---------------------------
CITIES = [
    "Delhi,IN",
    "Bengaluru,IN",
    "Ranchi,IN",
    "Dehradun,IN",
    "Mumbai,IN",
    "Kolkata,IN",
    "Chennai,IN",
    "Tokyo,JP",
    "Osaka,JP",
    "New York,US",
    "London,GB",
    "Sydney,AU"
]

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "36b9799bd833402eb7aba4a213eb4195")
AQICN_API_KEY = os.getenv("AQICN_API_KEY", "049bf346a0c63bc693ead5bbd3d1d08f248a646a")
DB_FILE = os.getenv("DB_FILE", "microclimate.db")
LOG_FILE = os.getenv("LOG_FILE", "collector.log")

# ---------------------------
# Logging setup
# ---------------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ---------------------------
# DB utilities
# ---------------------------
CREATE_READINGS_SQL = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime TEXT NOT NULL,
    city TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    temperature REAL,
    humidity REAL,
    weather TEXT,
    aqi INTEGER,
    aqi_source TEXT
);
"""

CREATE_META_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

def init_db(db_path: str = DB_FILE):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(CREATE_READINGS_SQL)
    cur.execute(CREATE_META_SQL)
    conn.commit()
    conn.close()

def insert_reading(row: Dict, db_path: str = DB_FILE):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Avoid duplicate entries for same datetime + city
    cur.execute("""
        SELECT COUNT(*) FROM readings
        WHERE datetime = ? AND city = ?
    """, (row["datetime"], row["city"]))
    count = cur.fetchone()[0]

    if count == 0:
        cur.execute("""
            INSERT INTO readings (datetime, city, latitude, longitude, temperature, humidity, weather, aqi, aqi_source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row["datetime"],
            row["city"],
            row.get("lat"),
            row.get("lon"),
            row.get("temp"),
            row.get("humidity"),
            row.get("weather_desc"),
            row.get("aqi"),
            row.get("aqi_source"),
        ))
        conn.commit()
        print(f"✅ Added: {row['city']} ({row['temp']}°C, AQI={row['aqi']}) at {row['datetime']}")
    else:
        print(f"⚠️ Duplicate ignored: {row['city']} at {row['datetime']}")

    conn.close()

# ---------------------------
# Networking utilities
# ---------------------------
def get_with_retries(url: str, params: dict = None, retries: int = 3, timeout: int = 10) -> Optional[dict]:
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            wait = (2 ** i) + random.random()
            logging.warning("Request failed (%s). Retry %d/%d in %.1fs", e, i+1, retries, wait)
            time.sleep(wait)
    logging.error("Failed to fetch URL after %d retries: %s", retries, url)
    return None

# ---------------------------
# API helpers
# ---------------------------
def fetch_aqi_by_city(city: str) -> Optional[Dict]:
    url = f"https://api.waqi.info/feed/{city}/"
    params = {"token": AQICN_API_KEY}
    return get_with_retries(url, params=params)

def fetch_aqi_by_coords(lat: float, lon: float) -> Optional[Dict]:
    url = f"https://api.waqi.info/feed/geo:{lat};{lon}/"
    params = {"token": AQICN_API_KEY}
    return get_with_retries(url, params=params)

def fetch_weather_for_city(city: str) -> Optional[Dict]:
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": city, "appid": OPENWEATHER_API_KEY, "units": "metric"}
    return get_with_retries(url, params=params)

# ---------------------------
# Main collector logic
# ---------------------------
def collect_for_city(city: str):
    try:
        print(f"\n🌍 Fetching weather + AQI for {city}...")
        weather = fetch_weather_for_city(city)
        if not weather or "main" not in weather:
            logging.error("Weather fetch failed for %s", city)
            print(f"❌ Failed to fetch weather for {city}")
            return

        lat = weather.get("coord", {}).get("lat")
        lon = weather.get("coord", {}).get("lon")

        # AQI lookup
        aqi_value = None
        aqi_source = None
        aqi_data = fetch_aqi_by_city(city)

        if aqi_data and aqi_data.get("status") == "ok":
            aqi_value = aqi_data["data"].get("aqi")
            aqi_source = "city"
        elif lat and lon:
            aqi_data = fetch_aqi_by_coords(lat, lon)
            if aqi_data and aqi_data.get("status") == "ok":
                aqi_value = aqi_data["data"].get("aqi")
                aqi_source = "coords"

        record = {
            "datetime": datetime.now(timezone.utc).isoformat(),
            "city": city,
            "lat": lat,
            "lon": lon,
            "temp": weather["main"].get("temp"),
            "humidity": weather["main"].get("humidity"),
            "weather_desc": weather["weather"][0].get("description") if weather.get("weather") else None,
            "aqi": aqi_value,
            "aqi_source": aqi_source
        }

        insert_reading(record)
        logging.info("Inserted reading for %s | temp=%s humidity=%s aqi=%s (src=%s)",
                     city, record["temp"], record["humidity"], record["aqi"], record["aqi_source"])

    except Exception as exc:
        logging.exception("Error collecting for %s: %s", city, exc)

# ---------------------------
# Entrypoints
# ---------------------------
def run_once():
    print("\n🚀 Running collector once for all cities...\n")
    init_db()
    for city in CITIES:
        collect_for_city(city)
    print("\n✅ Collection complete! Check 'microclimate.db' and 'collector.log' for details.\n")

def run_periodic(interval_seconds: int = 3600):
    init_db()
    logging.info("Starting periodic collector for cities: %s", CITIES)
    while True:
        start = time.time()
        for city in CITIES:
            collect_for_city(city)
        elapsed = time.time() - start
        sleep_for = max(0, interval_seconds - elapsed)
        logging.info("Cycle finished in %.1fs, sleeping %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)

if __name__ == "__main__":
    if os.getenv("RUN_ONCE", "1") == "1":
        run_once()
    else:
        run_periodic(3600)
