import streamlit as st
import pandas as pd
import sqlite3
from datetime import timedelta
import plotly.express as px

# ---------------------------
# CONFIGURATION
# ---------------------------
DB_FILE = "microclimate.db"

st.set_page_config(page_title="🌦️ Smart Microclimate Dashboard", layout="wide")

# ---------------------------
# Helper: Load Data
# ---------------------------
@st.cache_data(ttl=60)
def load_data(limit_days: int = 30):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query("SELECT * FROM readings ORDER BY datetime DESC", conn, parse_dates=["datetime"])
    conn.close()

    if df.empty:
        return df

    # Ensure timezone-aware datetime (UTC)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")

    # Drop duplicates (keep last for each city/timestamp)
    df = df.drop_duplicates(subset=["datetime", "city"], keep="last")

    # Limit to recent days
    if limit_days:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=limit_days)
        df = df[df["datetime"] >= cutoff]

    # Clean up nulls and bad data
    df = df.dropna(subset=["temperature", "humidity"])

    return df

# ---------------------------
# Load data
# ---------------------------
df = load_data()

st.title("🌍 Real-Time Multi-City Microclimate Dashboard")
st.caption("📡 Data from OpenWeatherMap + AQICN + SQLite")

# ---------------------------
# No data check
# ---------------------------
if df.empty:
    st.warning("⚠️ No data found yet.\n\nRun your `collector_multi_db.py` script first to start collecting readings.")
    st.stop()

# ---------------------------
# Sidebar controls
# ---------------------------
with st.sidebar:
    st.header("⚙️ Controls")
    limit_days = st.slider("Show last N days", 1, 60, 30)

    city_options = sorted(df["city"].unique().tolist())
    city = st.selectbox("🌆 Select City", city_options)
    df = df[df["city"] == city]

    st.write(f"**Showing data for:** {city}")

    # Optional filters
    min_temp = st.number_input("Min Temperature (°C)", -10, 50, -10)
    max_temp = st.number_input("Max Temperature (°C)", -10, 50, 50)
    df = df[(df["temperature"] >= min_temp) & (df["temperature"] <= max_temp)]

    # Apply date filter again
    df = df[df["datetime"] >= (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=limit_days))]

# ---------------------------
# KPI Section
# ---------------------------
latest = df.iloc[-1]
col1, col2, col3, col4 = st.columns(4)

col1.metric("🌡️ Temperature (°C)", f"{latest['temperature']:.1f}")
col2.metric("💧 Humidity (%)", f"{latest['humidity']}")
col3.metric("🌤️ Weather", latest["weather"])
aqi_val = latest.get("aqi", None)

# AQI Category Logic
def get_aqi_category(aqi):
    if pd.isna(aqi):
        return "Unavailable", "gray"
    if aqi <= 50:
        return "Good", "green"
    elif aqi <= 100:
        return "Moderate", "yellow"
    elif aqi <= 150:
        return "Unhealthy (Sensitive)", "orange"
    elif aqi <= 200:
        return "Unhealthy", "red"
    elif aqi <= 300:
        return "Very Unhealthy", "purple"
    else:
        return "Hazardous", "maroon"

aqi_status, color = get_aqi_category(aqi_val)
col4.markdown(f"<h3 style='color:{color};'>AQI: {aqi_val} ({aqi_status})</h3>", unsafe_allow_html=True)

# ---------------------------
# Charts
# ---------------------------
st.subheader(f"📈 Temperature & Humidity Trends — {city}")

temp_chart = px.line(
    df,
    x="datetime",
    y="temperature",
    title=f"Temperature Variation in {city} (°C)",
    markers=True,
    template="plotly_dark"
)
st.plotly_chart(temp_chart, use_container_width=True)

humid_chart = px.line(
    df,
    x="datetime",
    y="humidity",
    title=f"Humidity Variation in {city} (%)",
    markers=True,
    template="plotly_dark"
)
st.plotly_chart(humid_chart, use_container_width=True)

# ---- AQI Chart ----
if "aqi" in df.columns:
    st.subheader(f"🌫️ Air Quality Index (AQI) Over Time — {city}")
    aqi_chart = px.line(
        df,
        x="datetime",
        y="aqi",
        title=f"Air Quality Index (AQI) — {city}",
        markers=True,
        template="plotly_dark"
    )
    st.plotly_chart(aqi_chart, use_container_width=True)

# ---- Weather Distribution ----
st.subheader(f"☁️ Weather Condition Distribution — {city}")
if "weather" in df.columns and not df["weather"].isna().all():
    weather_counts = df["weather"].value_counts().reset_index()
    weather_counts.columns = ["Weather", "Count"]
    weather_fig = px.pie(
        weather_counts,
        values="Count",
        names="Weather",
        title=f"Weather Condition Distribution — {city}"
    )
    st.plotly_chart(weather_fig, use_container_width=True)

# ---- Data Table ----
st.subheader(f"🧾 Recent Records — {city}")
st.dataframe(df.tail(50).sort_values(by="datetime", ascending=False))

# ---- Export ----
st.download_button(
    "📥 Download Full Dataset (CSV)",
    data=df.to_csv(index=False).encode("utf-8"),
    file_name=f"microclimate_data_{city}.csv",
    mime="text/csv"
)

st.success("✅ Dashboard updated successfully with live multi-city microclimate data!")
