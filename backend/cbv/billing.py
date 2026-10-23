"""The paid plan of a hosted site, Plus, sold through Paddle Billing.

Paddle is the merchant of record: the reader buys Plus from Paddle, which charges them, adds the
taxes of their country and invoices them; the site never sees a card. Paddle tells the site what
happens to each subscription through signed webhooks (``apply``), and the site keeps only what it
needs to know an account's plan: Paddle's ids for the customer and the subscription, its status
and dates. The invoices, the card and cancelling are in Paddle's customer portal (``portal``).

Plus gives no ads, more books and storage (config.PLUS_*) and an unlimited daily trainer. A free
account may start config.FREE_TRAINER_SESSIONS trainer sessions, once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from . import config, library, users

log = logging.getLogger(__name__)

# The statuses of a subscription that give Plus. past_due: a payment failed and Paddle is trying
# again; the reader keeps Plus meanwhile.
PLUS_STATUSES = {"active", "trialing", "past_due"}
# How old a webhook's signature may be (seconds). Replaying one within it changes nothing: events
# are applied by when they happened.
TOLERANCE = 300
PRICE_SECONDS = 3600  # Plus's price is asked of Paddle at most this often

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    trainer_sessions INTEGER NOT NULL DEFAULT 0,  -- started on the free plan
    customer TEXT,  -- Paddle's ids
    subscription TEXT UNIQUE,
    status TEXT,
    until TEXT,  -- the end of the period paid for
    cancel_at TEXT,  -- a cancellation the reader asked for, from then
    changed_at TEXT  -- when the last event kept happened
);
"""


class Unavailable(Exception):
    """Paddle couldn't be reached, or refused what was asked."""


@dataclass
class Plan:
    plus: bool = False
    status: str | None = None
    until: str | None = None
    cancel_at: str | None = None
    customer: str | None = None
    subscription: str | None = None
    trainer_sessions: int = 0


_ready: set[str] = set()


@contextmanager
def _db():
    with users.connect() as conn:
        path = str(library.DATA_DIR / "users.db")
        if path not in _ready:
            conn.executescript(_SCHEMA)
            _ready.add(path)
        yield conn


def plan(user: str) -> Plan:
    """An account's plan (the local reader has none, and no limits either)."""
    if not config.HOSTED:
        return Plan()
    with _db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE user_id = ?", (user,)).fetchone()
    if row is None:
        return Plan()
    return Plan(row["status"] in PLUS_STATUSES, row["status"], row["until"], row["cancel_at"],
                row["customer"], row["subscription"], row["trainer_sessions"])


def limits(user: str) -> tuple[int, int]:
    """The most books, and megabytes of book files, an account may keep (0: no limit)."""
    if plan(user).plus:
        return config.PLUS_MAX_BOOKS, config.PLUS_MAX_STORAGE_MB
    return config.MAX_BOOKS, config.MAX_STORAGE_MB


def trainer_left(user: str) -> int | None:
    """How many more trainer sessions an account may start (None: as many as it likes)."""
    if not (config.SELLING and config.FREE_TRAINER_SESSIONS):
        return None
    p = plan(user)
    return None if p.plus else max(0, config.FREE_TRAINER_SESSIONS - p.trainer_sessions)


def trainer_started(user: str) -> None:
    """Counts a trainer session an account started, if it has only so many."""
    if trainer_left(user) is not None:
        with _db() as conn:
            conn.execute("INSERT INTO plans (user_id, trainer_sessions) VALUES (?, 1) ON CONFLICT (user_id) "
                         "DO UPDATE SET trainer_sessions = trainer_sessions + 1", (user,))


def checkout(user: users.User) -> dict | None:
    """What the browser opens Paddle's checkout with (None: Plus can't be bought, or is had)."""
    if not config.SELLING or plan(user.id).plus:
        return None
    # The account comes back in the subscription's custom data (see apply).
    return {"token": config.PADDLE_CLIENT_TOKEN, "price": config.PADDLE_PRICE, "sandbox": config.PADDLE_SANDBOX,
            "email": user.email, "user": user.id}


# --- What Paddle says ---

def verify(body: bytes, header: str | None, now: float | None = None) -> bool:
    """Whether a webhook comes from Paddle: its Paddle-Signature header (``ts=…;h1=…``) signs the
    time and the body with the notification destination's secret. While Paddle rotates the
    secret, more than one h1 comes."""
    if not header or not config.PADDLE_WEBHOOK_SECRET:
        return False
    parts = [part.split("=", 1) for part in header.split(";") if "=" in part]
    ts = next((value for key, value in parts if key == "ts"), "")
    if not ts.isdigit() or abs((time.time() if now is None else now) - int(ts)) > TOLERANCE:
        return False
    signed = hmac.new(config.PADDLE_WEBHOOK_SECRET.encode(), ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    return any(key == "h1" and hmac.compare_digest(signed, value) for key, value in parts)


def apply(event: dict) -> None:
    """Keeps what a webhook says of a subscription; other events are of no use here. Paddle may
    send an event more than once, or after a later one: one older than what is kept changes nothing."""
    if not str(event.get("event_type", "")).startswith("subscription."):
        return
    sub = event.get("data") or {}
    occurred = _time(event.get("occurred_at"))
    if not sub.get("id") or occurred is None:
        log.warning("a webhook from Paddle without a subscription or a time: %s", event.get("event_id"))
        return
    status = sub.get("status")
    change = sub.get("scheduled_change") or {}
    until = (sub.get("current_billing_period") or {}).get("ends_at")
    cancel_at = change.get("effective_at") if change.get("action") == "cancel" else None
    custom = sub.get("custom_data")
    with _db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE subscription = ?", (sub["id"],)).fetchone()
        user = row["user_id"] if row else custom.get("user") if isinstance(custom, dict) else None
        if not isinstance(user, str) or not user:
            log.warning("Paddle's subscription %s names no account", sub["id"])
            return
        kept = conn.execute("SELECT * FROM plans WHERE user_id = ?", (user,)).fetchone()
        if kept is not None:
            if kept["subscription"] == sub["id"] and (_time(kept["changed_at"]) or occurred) > occurred:
                return
            # An account with two subscriptions (bought twice) keeps Plus while one gives it.
            if kept["subscription"] not in (None, sub["id"]) and kept["status"] in PLUS_STATUSES and status not in PLUS_STATUSES:
                return
        try:
            conn.execute(
                "INSERT INTO plans (user_id, customer, subscription, status, until, cancel_at, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (user_id) DO UPDATE SET customer = excluded.customer, subscription = excluded.subscription, "
                "status = excluded.status, until = excluded.until, cancel_at = excluded.cancel_at, changed_at = excluded.changed_at",
                (user, sub.get("customer_id"), sub["id"], status, until, cancel_at, event["occurred_at"]))
        except sqlite3.IntegrityError:  # no such account (deleted since)
            log.warning("Paddle's subscription %s is of no account here (%s)", sub["id"], user)


def _time(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


# --- What the site asks of Paddle ---

def _api(method: str, path: str, body: dict | None = None) -> dict:
    base = "https://sandbox-api.paddle.com" if config.PADDLE_SANDBOX else "https://api.paddle.com"
    request = urllib.request.Request(
        base + path, method=method, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {config.PADDLE_API_KEY}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise Unavailable(str(e)) from e


def portal(user: str) -> dict | None:
    """Links into Paddle's customer portal for an account's subscription: its overview (invoices,
    the card, cancelling) and the cancellation itself. They work for a short time: ask each time.
    None: the account never bought Plus."""
    p = plan(user)
    if not (config.SELLING and p.customer):
        return None
    urls = _api("POST", f"/customers/{p.customer}/portal-sessions",
                {"subscription_ids": [p.subscription]} if p.subscription else {})["data"]["urls"]
    cancel = next((s.get("cancel_subscription") for s in urls.get("subscriptions") or []), None)
    return {"overview": urls["general"]["overview"], "cancel": cancel if p.plus else None}


def end(user: str) -> None:
    """Cancels an account's subscription at once (the account is being deleted or closed), so
    Paddle doesn't charge it again. Raises Unavailable if Paddle can't be told."""
    p = plan(user)
    if not p.subscription or p.status == "canceled":
        return
    if not config.SELLING:
        raise Unavailable("the Paddle settings are missing")
    _api("POST", f"/subscriptions/{p.subscription}/cancel", {"effective_from": "immediately"})
    with _db() as conn:
        conn.execute("UPDATE plans SET status = 'canceled', cancel_at = NULL WHERE user_id = ?", (user,))


_price: tuple[float, dict | None] = (0.0, None)


def price() -> dict | None:
    """Plus's price as Paddle has it: the amount in the currency's smallest unit, the currency,
    how often it renews and any free trial (None: not on sale, or Paddle never answered)."""
    global _price
    if not config.SELLING:
        return None
    asked, known = _price
    if known is not None and time.monotonic() - asked < PRICE_SECONDS:
        return known
    try:
        data = _api("GET", f"/prices/{config.PADDLE_PRICE}")["data"]
        cycle, trial = data.get("billing_cycle") or {}, data.get("trial_period") or {}
        known = {"amount": data["unit_price"]["amount"], "currency": data["unit_price"]["currency_code"],
                 "interval": cycle.get("interval"), "frequency": cycle.get("frequency"),
                 "trial_interval": trial.get("interval"), "trial_frequency": trial.get("frequency")}
    except (Unavailable, KeyError, TypeError) as e:
        log.warning("Paddle didn't give Plus's price: %s", e)
        return known
    _price = (time.monotonic(), known)
    return known
