import os
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.ledger import create_account, get_balance, get_connection, init_db
from app.payments import (
    IdempotencyConflict,
    InvalidTransition,
    complete_payment,
    create_payment,
    fail_payment,
    get_payment,
    init_payments_db,
    refund_payment,
)

DB_PATH = os.environ.get("PAYMENTS_DB", "payments.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = get_connection(DB_PATH)
    init_db(conn)
    init_payments_db(conn)
    conn.close()
    yield


app = FastAPI(title="Payments Service", lifespan=lifespan)


def get_db():
    conn = get_connection(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


# ---------- Request models ----------

class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class PaymentIn(BaseModel):
    payer_account_id: int
    merchant_account_id: int
    amount_cents: int = Field(gt=0)


# ---------- Accounts ----------

@app.post("/accounts", status_code=201)
def post_account(body: AccountIn, conn=Depends(get_db)):
    try:
        account_id = create_account(conn, body.name)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Account name already exists")
    return {"id": account_id, "name": body.name}


@app.get("/accounts/{account_id}/balance")
def get_account_balance(account_id: int, conn=Depends(get_db)):
    exists = conn.execute(
        "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
    ).fetchone()
    if not exists:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account_id": account_id, "balance_cents": get_balance(conn, account_id)}


# ---------- Payments ----------

@app.post("/payments", status_code=201)
def post_payment(
    body: PaymentIn,
    idempotency_key: str = Header(..., min_length=1, max_length=255),
    conn=Depends(get_db),
):
    try:
        return create_payment(
            conn,
            idempotency_key,
            body.payer_account_id,
            body.merchant_account_id,
            body.amount_cents,
        )
    except IdempotencyConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Unknown payer or merchant account")


@app.get("/payments/{payment_id}")
def read_payment(payment_id: int, conn=Depends(get_db)):
    payment = get_payment(conn, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


def _transition(conn, payment_id, action):
    if get_payment(conn, payment_id) is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    try:
        return action(conn, payment_id)
    except InvalidTransition as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.post("/payments/{payment_id}/complete")
def post_complete(payment_id: int, conn=Depends(get_db)):
    return _transition(conn, payment_id, complete_payment)


@app.post("/payments/{payment_id}/fail")
def post_fail(payment_id: int, conn=Depends(get_db)):
    return _transition(conn, payment_id, fail_payment)


@app.post("/payments/{payment_id}/refund")
def post_refund(payment_id: int, conn=Depends(get_db)):
    return _transition(conn, payment_id, refund_payment)