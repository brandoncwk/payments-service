import pytest
from fastapi.testclient import TestClient

from app.ledger import get_connection, init_db
from app.main import app, get_db
from app.payments import init_payments_db


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = get_connection(db_path)
    init_db(conn)
    init_payments_db(conn)
    conn.close()

    def override_get_db():
        c = get_connection(db_path)
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def accounts(client):
    alice = client.post("/accounts", json={"name": "alice"}).json()["id"]
    merchant = client.post("/accounts", json={"name": "merchant"}).json()["id"]
    return alice, merchant


def pay(client, key, alice, merchant, amount=5000):
    return client.post(
        "/payments",
        headers={"Idempotency-Key": key},
        json={
            "payer_account_id": alice,
            "merchant_account_id": merchant,
            "amount_cents": amount,
        },
    )


def test_full_payment_flow(client, accounts):
    alice, merchant = accounts
    r = pay(client, "k1", alice, merchant)
    assert r.status_code == 201
    payment_id = r.json()["id"]

    r = client.post(f"/payments/{payment_id}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "succeeded"

    r = client.get(f"/accounts/{merchant}/balance")
    assert r.json()["balance_cents"] == 5000


def test_retry_with_same_key_returns_same_payment(client, accounts):
    alice, merchant = accounts
    first = pay(client, "k1", alice, merchant).json()
    second = pay(client, "k1", alice, merchant).json()
    assert first["id"] == second["id"]


def test_same_key_different_amount_is_conflict(client, accounts):
    alice, merchant = accounts
    pay(client, "k1", alice, merchant, 5000)
    r = pay(client, "k1", alice, merchant, 9999)
    assert r.status_code == 409


def test_missing_idempotency_key_rejected(client, accounts):
    alice, merchant = accounts
    r = client.post(
        "/payments",
        json={
            "payer_account_id": alice,
            "merchant_account_id": merchant,
            "amount_cents": 5000,
        },
    )
    assert r.status_code == 422


def test_negative_amount_rejected(client, accounts):
    alice, merchant = accounts
    r = pay(client, "k1", alice, merchant, -100)
    assert r.status_code == 422


def test_complete_twice_is_conflict(client, accounts):
    alice, merchant = accounts
    pid = pay(client, "k1", alice, merchant).json()["id"]
    client.post(f"/payments/{pid}/complete")
    r = client.post(f"/payments/{pid}/complete")
    assert r.status_code == 409


def test_unknown_payment_is_404(client):
    assert client.get("/payments/999").status_code == 404
    assert client.post("/payments/999/complete").status_code == 404


def test_unknown_account_is_400(client, accounts):
    alice, _ = accounts
    r = pay(client, "k1", alice, 999)
    assert r.status_code == 400