import sqlite3
from datetime import datetime

DB_PATH = "signals.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT,
            token_name TEXT,
            token_symbol TEXT,
            market_cap REAL,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_signal(token_address, token_name, token_symbol, market_cap):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO signals (token_address, token_name, token_symbol, market_cap, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (token_address, token_name, token_symbol, market_cap, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()

def get_all_signals():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token_address, token_name, token_symbol, market_cap, timestamp FROM signals")
    rows = c.fetchall()
    conn.close()
    return rows
