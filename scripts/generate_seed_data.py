#!/usr/bin/env python3
"""One-off generator for the fixed Customer 360 seed dataset.

Produces ~100 correlated records for each of the five ODCS source objects
and writes them as CSVs under data/seed/. The output is checked into git as
frozen fixture data (like the ODPS/ODCS documents) — re-run this script only
if you intend to replace the fixtures; a fixed random seed keeps a given
Python version's output stable, but the *committed CSVs*, not this script,
are the source of truth the agents read at runtime.

Usage: python scripts/generate_seed_data.py
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "agents"))
from common.models import REFERENCE_DATE, SEED_DIR  # noqa: E402

RNG = random.Random(42)

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
    "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
    "Thomas", "Sarah", "Charles", "Karen", "Emma", "Olivia", "Noah", "Liam", "Ava",
    "Sophia", "Mia", "Lucas", "Ethan", "Amelia",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
]
STREETS = ["Bankside Avenue", "Market Street", "Harbor Road", "Elm Street", "Kings Way",
           "Church Lane", "Mill Road", "Park Avenue", "Station Road", "Victoria Street"]
CITIES = ["Helsinki", "Espoo", "Tampere", "Turku", "Oulu", "Vantaa", "Lahti", "Kuopio"]
BRANCHES = ["BR-101", "BR-102", "BR-103", "BR-104", "BR-105"]
MERCHANT_CATEGORIES = ["5411", "5812", "5541", "5732", "6011", "5651"]
PRODUCT_CATALOG = [
    ("MORT-FIX-25Y", "LOAN"), ("MORT-VAR-20Y", "LOAN"), ("LOAN-PERSONAL", "LOAN"),
    ("CARD-GOLD", "CARD"), ("CARD-CLASSIC", "CARD"), ("CARD-PLATINUM", "CARD"),
    ("DEP-SAVINGS", "DEPOSIT"), ("DEP-TERM-12M", "DEPOSIT"),
    ("INS-HOME", "INSURANCE"), ("INS-LIFE", "INSURANCE"),
]


def weighted_choice(options: dict[str, float]) -> str:
    return RNG.choices(list(options), weights=list(options.values()), k=1)[0]


def random_date(days_back_min: int, days_back_max: int):
    days_back = RNG.randint(days_back_min, days_back_max)
    return REFERENCE_DATE - timedelta(days=days_back)


def random_datetime(days_back_min: int, days_back_max: int):
    d = random_date(days_back_min, days_back_max)
    return d.isoformat() + f"T{RNG.randint(0, 23):02d}:{RNG.randint(0, 59):02d}:00"


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    path = SEED_DIR / f"{name}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows):>3} rows -> {path.relative_to(REPO_ROOT)}")


def gen_parties(n: int = 100) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        first, last = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        rows.append({
            "party_id": f"PTY-{i:08d}",
            "full_name": f"{first} {last}",
            "date_of_birth": random_date(20 * 365, 76 * 365).isoformat(),
            "national_id": f"FI-{900000000 + i}",
            "email": f"{first.lower()}.{last.lower()}{i}@example.com",
            "phone": f"+358-4{RNG.randint(10000000, 99999999)}",
            "address": f"{RNG.randint(1, 200)} {RNG.choice(STREETS)}, {RNG.choice(CITIES)}",
            "marketing_consent": RNG.random() < 0.6,
            "kyc_status": weighted_choice({"VERIFIED": 0.8, "PENDING": 0.15, "EXPIRED": 0.05}),
            "risk_rating": weighted_choice({"LOW": 0.7, "MEDIUM": 0.25, "HIGH": 0.05}),
        })
    return rows


def gen_accounts(parties: list[dict]) -> list[dict]:
    """70 parties get 1 account, the next 15 get 2, the last 15 get none -> 100 accounts."""
    rows = []
    idx = 1
    for party in parties[:70]:
        rows.append(_account(idx, party["party_id"]))
        idx += 1
    for party in parties[70:85]:
        for _ in range(2):
            rows.append(_account(idx, party["party_id"]))
            idx += 1
    return rows


def _account(idx: int, party_id: str) -> dict:
    account_type = weighted_choice({"CURRENT": 0.5, "SAVINGS": 0.35, "TERM_DEPOSIT": 0.15})
    balance_range = {"CURRENT": (100, 5000), "SAVINGS": (500, 50000), "TERM_DEPOSIT": (5000, 100000)}[account_type]
    return {
        "account_id": f"ACC-{idx:09d}",
        "party_id": party_id,
        "account_type": account_type,
        "account_status": weighted_choice({"ACTIVE": 0.85, "DORMANT": 0.10, "CLOSED": 0.05}),
        "balance": round(RNG.uniform(*balance_range), 2),
        "currency": weighted_choice({"EUR": 0.9, "USD": 0.1}),
        "branch_code": RNG.choice(BRANCHES),
        "opened_date": random_date(30, 10 * 365).isoformat(),
    }


def gen_transactions(accounts: list[dict], n: int = 100) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        account = RNG.choice(accounts)
        txn_type = weighted_choice({"DEBIT": 0.7, "CREDIT": 0.3})
        amount_range = (5, 2000) if txn_type == "DEBIT" else (50, 5000)
        channel = weighted_choice({"MOBILE": 0.4, "ONLINE": 0.25, "BRANCH": 0.15, "ATM": 0.15, "POS": 0.05})
        rows.append({
            "transaction_id": f"TXN-{i:010d}",
            "account_id": account["account_id"],
            "txn_type": txn_type,
            "amount": round(RNG.uniform(*amount_range), 2),
            "currency": account["currency"],
            "channel": channel,
            "merchant_category": RNG.choice(MERCHANT_CATEGORIES) if channel in ("POS", "ONLINE") else "",
            "txn_timestamp": random_datetime(0, 180),
        })
    return rows


def gen_tickets(parties: list[dict], n: int = 100) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        party = RNG.choice(parties)
        status = weighted_choice({"RESOLVED": 0.5, "CLOSED": 0.3, "IN_PROGRESS": 0.12, "OPEN": 0.08})
        opened_ts = random_datetime(0, 365)
        resolved_ts, csat = "", ""
        if status in ("RESOLVED", "CLOSED"):
            from datetime import date as _date, datetime as _dt
            opened_dt = _dt.fromisoformat(opened_ts)
            resolved_dt = opened_dt + timedelta(days=RNG.randint(1, 14))
            resolved_ts = min(resolved_dt, _dt.combine(REFERENCE_DATE, _dt.min.time())).isoformat()
            csat = RNG.choices([1, 2, 3, 4, 5], weights=[0.05, 0.05, 0.15, 0.35, 0.40])[0]
        rows.append({
            "ticket_id": f"TCK-{i:07d}",
            "party_id": party["party_id"],
            "channel": weighted_choice({"PHONE": 0.3, "EMAIL": 0.3, "CHAT": 0.3, "BRANCH": 0.1}),
            "category": weighted_choice({"SERVICE_REQUEST": 0.6, "COMPLAINT": 0.3, "FRAUD_DISPUTE": 0.1}),
            "severity": weighted_choice({"LOW": 0.4, "MEDIUM": 0.35, "HIGH": 0.2, "CRITICAL": 0.05}),
            "status": status,
            "opened_ts": opened_ts,
            "resolved_ts": resolved_ts,
            "csat_score": csat,
        })
    return rows


def gen_holdings(parties: list[dict], n: int = 100) -> list[dict]:
    rows = []
    for i in range(1, n + 1):
        party = RNG.choice(parties)
        product_code, product_type = RNG.choice(PRODUCT_CATALOG)
        status = weighted_choice({"ACTIVE": 0.75, "MATURED": 0.15, "CANCELLED": 0.10})
        start_date = random_date(30, 15 * 365)
        end_date = ""
        if status != "ACTIVE":
            candidate = start_date + timedelta(days=RNG.randint(30, 3650))
            end_date = min(candidate, REFERENCE_DATE).isoformat()
        rows.append({
            "holding_id": f"HLD-{i:07d}",
            "party_id": party["party_id"],
            "product_code": product_code,
            "product_type": product_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date,
            "status": status,
        })
    return rows


def main() -> None:
    parties = gen_parties()
    accounts = gen_accounts(parties)
    transactions = gen_transactions(accounts)
    tickets = gen_tickets(parties)
    holdings = gen_holdings(parties)

    write_csv("party_details", list(parties[0].keys()), parties)
    write_csv("customer_account", list(accounts[0].keys()), accounts)
    write_csv("transaction_details", list(transactions[0].keys()), transactions)
    write_csv("customer_ticket_details", list(tickets[0].keys()), tickets)
    write_csv("customer_product_details", list(holdings[0].keys()), holdings)


if __name__ == "__main__":
    main()
