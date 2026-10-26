import pytest
from app.ledger import (
    get_connection, init_db, create_account, record_transaction, get_balance
)


@pytest.fixture
def conn():
    c = get_connection()
    init_db(c)
    return c


def test_transfer_updates_balances(conn):
    alice = create_account(conn, "alice")
    merchant = create_account(conn, "merchant")
    record_transaction(conn, "coffee", [(alice, -450), (merchant, 450)])
    assert get_balance(conn, alice) == -450
    assert get_balance(conn, merchant) == 450


def test_unbalanced_transaction_rejected(conn):
    alice = create_account(conn, "alice")
    merchant = create_account(conn, "merchant")
    with pytest.raises(ValueError):
        record_transaction(conn, "bad", [(alice, -450), (merchant, 400)])


def test_single_entry_rejected(conn):
    alice = create_account(conn, "alice")
    with pytest.raises(ValueError):
        record_transaction(conn, "bad", [(alice, 0)])