import pytest
from app.ledger import get_connection, init_db, create_account, get_balance
from app.payments import (
    init_payments_db, create_payment, complete_payment, fail_payment,
    refund_payment, InvalidTransition, IdempotencyConflict,
)


@pytest.fixture
def setup():
    conn = get_connection()
    init_db(conn)
    init_payments_db(conn)
    alice = create_account(conn, "alice")
    merchant = create_account(conn, "merchant")
    return conn, alice, merchant


def test_complete_moves_money(setup):
    conn, alice, merchant = setup
    p = create_payment(conn, "key-1", alice, merchant, 5000)
    assert p["status"] == "pending"
    p = complete_payment(conn, p["id"])
    assert p["status"] == "succeeded"
    assert get_balance(conn, alice) == -5000
    assert get_balance(conn, merchant) == 5000


def test_same_key_returns_same_payment(setup):
    conn, alice, merchant = setup
    p1 = create_payment(conn, "key-1", alice, merchant, 5000)
    p2 = create_payment(conn, "key-1", alice, merchant, 5000)
    assert p1["id"] == p2["id"]
    count = conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    assert count == 1


def test_same_key_different_amount_rejected(setup):
    conn, alice, merchant = setup
    create_payment(conn, "key-1", alice, merchant, 5000)
    with pytest.raises(IdempotencyConflict):
        create_payment(conn, "key-1", alice, merchant, 9999)


def test_completing_twice_does_not_double_charge(setup):
    conn, alice, merchant = setup
    p = create_payment(conn, "key-1", alice, merchant, 5000)
    complete_payment(conn, p["id"])
    with pytest.raises(InvalidTransition):
        complete_payment(conn, p["id"])
    assert get_balance(conn, merchant) == 5000


def test_cannot_refund_pending_payment(setup):
    conn, alice, merchant = setup
    p = create_payment(conn, "key-1", alice, merchant, 5000)
    with pytest.raises(InvalidTransition):
        refund_payment(conn, p["id"])


def test_refund_restores_balances(setup):
    conn, alice, merchant = setup
    p = create_payment(conn, "key-1", alice, merchant, 5000)
    complete_payment(conn, p["id"])
    p = refund_payment(conn, p["id"])
    assert p["status"] == "refunded"
    assert get_balance(conn, alice) == 0
    assert get_balance(conn, merchant) == 0


def test_failed_payment_creates_no_ledger_entries(setup):
    conn, alice, merchant = setup
    p = create_payment(conn, "key-1", alice, merchant, 5000)
    fail_payment(conn, p["id"])
    entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    assert entries == 0