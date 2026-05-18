import os
import time
import threading
import sqlite3
from flask import Flask, render_template, jsonify
from web3 import Web3
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
RPC_URL = os.getenv("RPC_URL")
w3 = Web3(Web3.HTTPProvider(RPC_URL))
DB_PATH = "eth_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE,
            block_number INTEGER,
            from_address TEXT,
            to_address TEXT,
            value_eth REAL,
            gas INTEGER,
            tx_type TEXT,
            timestamp INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_number INTEGER UNIQUE,
            tx_count INTEGER,
            total_eth REAL,
            timestamp INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def classify_tx(tx):
    data = tx["input"].hex() if isinstance(tx["input"], bytes) else tx["input"]
    if tx["value"] > 0 and data == "0x":
        return "ETH Transfer"
    elif data.startswith("0xa9059cbb"):
        return "Token Transfer"
    elif data.startswith("0x095ea7b3"):
        return "Approve"
    elif data.startswith("0x38ed1739") or data.startswith("0x7ff36ab5"):
        return "Swap"
    else:
        return "Contract Call"

def save_transaction(tx, block_number, timestamp):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        eth_value = float(w3.from_wei(tx["value"], "ether"))
        tx_type = classify_tx(tx)
        c.execute('''
            INSERT OR IGNORE INTO transactions
            (hash, block_number, from_address, to_address, value_eth, gas, tx_type, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            tx["hash"].hex(),
            block_number,
            tx["from"],
            tx["to"],
            eth_value,
            tx["gas"],
            tx_type,
            timestamp
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

def save_block(block_number, tx_count, total_eth, timestamp):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            INSERT OR IGNORE INTO blocks
            (block_number, tx_count, total_eth, timestamp)
            VALUES (?, ?, ?, ?)
        ''', (block_number, tx_count, total_eth, timestamp))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Block DB Error: {e}")

def etl_pipeline():
    last_block = w3.eth.block_number
    print(f"ETL Pipeline started at block {last_block}")
    while True:
        try:
            current_block = w3.eth.block_number
            if current_block > last_block:
                block = w3.eth.get_block(current_block, full_transactions=True)
                timestamp = block["timestamp"]
                total_eth = 0
                for tx in block.transactions:
                    eth_val = float(w3.from_wei(tx["value"], "ether"))
                    total_eth += eth_val
                    save_transaction(tx, current_block, timestamp)
                save_block(current_block, len(block.transactions), total_eth, timestamp)
                print(f"Block {current_block}: {len(block.transactions)} txs indexed")
                last_block = current_block
            time.sleep(12)
        except Exception as e:
            print(f"Pipeline error: {e}")
            time.sleep(12)

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM transactions")
    total_txs = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM blocks")
    total_blocks = c.fetchone()[0]
    c.execute("SELECT SUM(value_eth) FROM transactions")
    total_eth = c.fetchone()[0] or 0
    c.execute("SELECT tx_type, COUNT(*) FROM transactions GROUP BY tx_type ORDER BY COUNT(*) DESC")
    tx_types = c.fetchall()
    c.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 20")
    recent = c.fetchall()
    conn.close()
    return {
        "total_txs": total_txs,
        "total_blocks": total_blocks,
        "total_eth": round(total_eth, 4),
        "tx_types": [{"type": t[0], "count": t[1]} for t in tx_types],
        "recent": [{
            "hash": r[1],
            "block": r[2],
            "from": r[3],
            "to": r[4],
            "value_eth": r[5],
            "gas": r[6],
            "type": r[7]
        } for r in recent]
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/stats")
def stats():
    return jsonify(get_stats())

if __name__ == "__main__":
    init_db()
    pipeline = threading.Thread(target=etl_pipeline, daemon=True)
    pipeline.start()
    app.run(host="0.0.0.0", port=5002, debug=False)
