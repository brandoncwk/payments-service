import sqlite3


def get_connection(path=":memory:"):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        description TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL REFERENCES transactions(id),
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        amount_cents INTEGER NOT NULL
    );
    """)
    conn.commit()


def create_account(conn, name):
    cur = conn.execute("INSERT INTO accounts (name) VALUES (?)", (name,))
    conn.commit()
    return cur.lastrowid


def record_transaction(conn, description, entries):
    """entries is a list of (account_id, amount_cents) tuples."""
    if len(entries) < 2:
        raise ValueError("A transaction needs at least 2 entries")
    if sum(amount for _, amount in entries) != 0:
        raise ValueError("Entries must sum to zero")

    cur = conn.execute(
        "INSERT INTO transactions (description) VALUES (?)", (description,)
    )
    txn_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO entries (transaction_id, account_id, amount_cents) VALUES (?, ?, ?)",
        [(txn_id, account_id, amount) for account_id, amount in entries],
    )
    conn.commit()
    return txn_id


def get_balance(conn, account_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM entries WHERE account_id = ?",
        (account_id,),
    ).fetchone()
    return row[0]