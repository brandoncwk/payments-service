import sqlite3
from app.ledger import record_transaction

VALID_TRANSITIONS = {
    "pending": {"succeeded", "failed"},
    "succeeded": {"refunded"},
    "failed": set(),
    "refunded": set(),
}


class InvalidTransition(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def init_payments_db(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        idempotency_key TEXT NOT NULL UNIQUE,
        payer_account_id INTEGER NOT NULL REFERENCES accounts(id),
        merchant_account_id INTEGER NOT NULL REFERENCES accounts(id),
        amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()


def get_payment(conn, payment_id):
    row = conn.execute(
        "SELECT * FROM payments WHERE id = ?", (payment_id,)
    ).fetchone()
    return dict(row) if row else None


def _get_by_key(conn, key):
    row = conn.execute(
        "SELECT * FROM payments WHERE idempotency_key = ?", (key,)
    ).fetchone()
    return dict(row) if row else None


def _same_request(existing, payer_id, merchant_id, amount_cents):
    return (
        existing["payer_account_id"] == payer_id
        and existing["merchant_account_id"] == merchant_id
        and existing["amount_cents"] == amount_cents
    )


def create_payment(conn, idempotency_key, payer_id, merchant_id, amount_cents):
    if amount_cents <= 0:
        raise ValueError("Amount must be positive")
    if payer_id == merchant_id:
        raise ValueError("Payer and merchant must differ")

    existing = _get_by_key(conn, idempotency_key)
    if existing is None:
        try:
            conn.execute(
                """INSERT INTO payments
                   (idempotency_key, payer_account_id, merchant_account_id, amount_cents)
                   VALUES (?, ?, ?, ?)""",
                (idempotency_key, payer_id, merchant_id, amount_cents),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Another request may have inserted this key a moment ago.
            conn.rollback()
            existing = _get_by_key(conn, idempotency_key)
            if existing is None:
                raise  # a different integrity problem, e.g. unknown account
        else:
            return _get_by_key(conn, idempotency_key)

    if not _same_request(existing, payer_id, merchant_id, amount_cents):
        raise IdempotencyConflict(
            "Idempotency key already used with different parameters"
        )
    return existing


def _move(conn, payment_id, new_status):
    """Change status if the transition is legal. Does NOT commit."""
    payment = get_payment(conn, payment_id)
    if payment is None:
        raise ValueError(f"Payment {payment_id} not found")
    if new_status not in VALID_TRANSITIONS[payment["status"]]:
        raise InvalidTransition(
            f"Cannot go from {payment['status']} to {new_status}"
        )
    cur = conn.execute(
        "UPDATE payments SET status = ? WHERE id = ? AND status = ?",
        (new_status, payment_id, payment["status"]),
    )
    if cur.rowcount != 1:
        raise InvalidTransition("Payment was modified concurrently")
    return payment


def complete_payment(conn, payment_id):
    try:
        p = _move(conn, payment_id, "succeeded")
        record_transaction(
            conn,
            f"payment {payment_id}",
            [(p["payer_account_id"], -p["amount_cents"]),
             (p["merchant_account_id"], p["amount_cents"])],
            commit=False,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_payment(conn, payment_id)


def fail_payment(conn, payment_id):
    try:
        _move(conn, payment_id, "failed")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_payment(conn, payment_id)


def refund_payment(conn, payment_id):
    try:
        p = _move(conn, payment_id, "refunded")
        # A refund is a NEW reversing transaction. We never edit history.
        record_transaction(
            conn,
            f"refund of payment {payment_id}",
            [(p["payer_account_id"], p["amount_cents"]),
             (p["merchant_account_id"], -p["amount_cents"])],
            commit=False,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_payment(conn, payment_id)