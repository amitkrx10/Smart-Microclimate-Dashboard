import sqlite3
import datetime

# Connect to your database
conn = sqlite3.connect("microclimate.db")
cur = conn.cursor()

# Check if the table exists (for safety)
cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = [t[0] for t in cur.fetchall()]
print("📊 Tables found in database:", tables)

# If your table exists, clean up data older than 30 days
if "weather_data" in tables:
    print("🧹 Cleaning old data (older than 30 days)...")

    cur.execute("""
        DELETE FROM weather_data
        WHERE datetime < datetime('now', '-30 days')
    """)

    conn.commit()
    print("✅ Cleanup complete! Old data removed successfully.")

else:
    print("❌ Table 'weather_data' not found. Please check your database.")

# Close connection
conn.close()

print("🔒 Database connection closed.")
