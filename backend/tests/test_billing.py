"""The hosted app's plans: Plus sold through Paddle, what each plan may keep and do, and the ads."""

import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cbv import billing, config, copyright, library
from cbv.main import app

from .test_accounts import browser, outbox, signed_up  # noqa: F401 (outbox: a fixture)
from .test_copyright import tiny_epub, upload

SECRET = "pdl_ntfset_secret"


@pytest.fixture
def paddle(outbox, monkeypatch):
    """Plus on sale, with Paddle's API answering from ``answers`` (by path) and its calls kept."""
    for name, value in {"SELLING": True, "PADDLE_API_KEY": "pdl_sdbx_apikey_x", "PADDLE_CLIENT_TOKEN": "test_token",
                        "PADDLE_PRICE": "pri_plus", "PADDLE_WEBHOOK_SECRET": SECRET, "PADDLE_SANDBOX": True,
                        "FREE_TRAINER_SESSIONS": 7}.items():
        monkeypatch.setattr(config, name, value)
    monkeypatch.setattr(billing, "_price", (0.0, None))
    calls, answers = [], {}

    def api(method, path, body=None):
        calls.append((method, path, body))
        answer = answers.get(path, {"data": {}})
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(billing, "_api", api)
    return SimpleNamespace(calls=calls, answers=answers)


def subscription(user: str, status="active", at="2026-10-21T10:00:00.000000Z", kind="subscription.updated",
                 sub="sub_01", cancel_at=None) -> dict:
    return {"event_id": f"evt_{at}", "event_type": kind, "occurred_at": at, "notification_id": "ntf_01", "data": {
        "id": sub, "status": status, "customer_id": "ctm_01", "custom_data": {"user": user},
        "current_billing_period": None if status == "canceled" else {"starts_at": "2026-10-21T10:00:00Z", "ends_at": "2026-11-21T10:00:00Z"},
        "scheduled_change": {"action": "cancel", "effective_at": cancel_at, "resume_at": None} if cancel_at else None,
    }}


def signature(body: bytes, ts: int | None = None, secret: str = SECRET) -> str:
    ts = int(time.time()) if ts is None else ts
    return f"ts={ts};h1=" + hmac.new(secret.encode(), f"{ts}:".encode() + body, hashlib.sha256).hexdigest()


def tell(event: dict, header: str | None = None):
    """Paddle's webhook, signed as Paddle signs it (or with ``header``)."""
    body = json.dumps(event).encode()
    headers = {"Content-Type": "application/json", "Paddle-Signature": header or signature(body)}
    # Paddle's servers send no Origin: the request isn't from a page of another site.
    return TestClient(app, base_url="https://testserver").post("/api/billing/webhook", content=body, headers=headers)


def plus(client) -> str:
    """Buys Plus for a signed-in account; its id."""
    user = client.get("/api/plan").json()["checkout"]["user"]
    assert tell(subscription(user, kind="subscription.created")).status_code == 200
    return user


def test_plus_is_bought_from_paddle_and_kept_from_its_webhooks(paddle, outbox):
    ana = signed_up(outbox)
    plan = ana.get("/api/plan").json()
    assert plan["plus"] is False and plan["selling"] is True and plan["manage"] is False and plan["trainer_left"] == 7
    checkout = plan["checkout"]
    assert checkout["token"] == "test_token" and checkout["price"] == "pri_plus" and checkout["sandbox"] is True
    assert checkout["email"] == "ana@example.com" and len(checkout["user"]) == 32
    user = checkout["user"]

    assert tell(subscription(user, kind="subscription.created")).status_code == 200
    plan = ana.get("/api/plan").json()
    assert plan["plus"] is True and plan["status"] == "active" and plan["until"] == "2026-11-21T10:00:00Z"
    assert plan["checkout"] is None and plan["trainer_left"] is None and plan["manage"] is True

    # Cancelled from Paddle's portal: Plus stays to the end of the period paid for.
    assert tell(subscription(user, at="2026-10-25T09:00:00.000000Z", cancel_at="2026-11-21T10:00:00Z")).status_code == 200
    # Paddle may deliver an older event late, or one twice: neither undoes what came after.
    tell(subscription(user, at="2026-10-22T09:00:00.000000Z"))
    plan = ana.get("/api/plan").json()
    assert plan["plus"] is True and plan["cancel_at"] == "2026-11-21T10:00:00Z"

    tell(subscription(user, status="canceled", at="2026-11-21T10:00:01.000000Z"))
    plan = ana.get("/api/plan").json()
    assert plan["plus"] is False and plan["status"] == "canceled" and plan["checkout"]["user"] == user


def test_only_paddle_can_tell_of_a_subscription(paddle, outbox, monkeypatch):
    ana = signed_up(outbox)
    user = ana.get("/api/plan").json()["checkout"]["user"]
    event = subscription(user)
    body = json.dumps(event).encode()
    assert tell(event, header="ts=1;h1=00").status_code == 401
    assert tell(event, header=signature(body, secret="someone else's")).status_code == 401
    assert tell(event, header=signature(body, ts=int(time.time()) - 600)).status_code == 401
    assert ana.get("/api/plan").json()["plus"] is False
    # While Paddle rotates the secret, it signs with the old and the new.
    old_and_new = signature(body, secret="the old one") + ";h1=" + signature(body).split("h1=")[1]
    assert tell(event, header=old_and_new).status_code == 200
    assert ana.get("/api/plan").json()["plus"] is True

    # Events of no account here, or of other things, change nothing.
    assert tell(subscription("0" * 32, sub="sub_02")).status_code == 200
    assert tell({**subscription("", sub="sub_03"), "event_type": "subscription.created"}).status_code == 200
    assert tell({"event_type": "transaction.completed", "occurred_at": "2026-10-21T10:00:00Z", "data": {"id": "txn_01"}}).status_code == 200

    monkeypatch.setattr(config, "SELLING", False)
    assert tell(event).status_code == 404


def test_a_free_account_tries_the_trainer_a_few_times(paddle, outbox, monkeypatch):
    monkeypatch.setattr(config, "FREE_TRAINER_SESSIONS", 2)
    sessions = iter([{"blocks": []}] + [{"blocks": [{"kind": "calculation"}]}] * 10)
    monkeypatch.setattr(library, "trainer_session", lambda user, test=False: next(sessions))
    ana = signed_up(outbox)
    # A library with nothing to train on starts no session, and spends none.
    assert ana.post("/api/trainer/session").json() == {"blocks": []}
    assert ana.get("/api/plan").json()["trainer_left"] == 2
    assert ana.post("/api/trainer/session").status_code == 200
    assert ana.post("/api/trainer/session?test=true").status_code == 200
    assert ana.get("/api/plan").json()["trainer_left"] == 0
    refused = ana.post("/api/trainer/session")
    assert refused.status_code == 402 and refused.json()["detail"] == "plus"
    # The rest of the trainer (its record, its books) stays open.
    assert ana.get("/api/trainer").status_code == 200

    plus(ana)
    for _ in range(3):
        assert ana.post("/api/trainer/session").status_code == 200

    # A site that doesn't sell Plus doesn't count.
    bob = signed_up(outbox, "bob@example.com")
    monkeypatch.setattr(config, "SELLING", False)
    assert bob.get("/api/plan").json()["trainer_left"] is None
    for _ in range(3):
        assert bob.post("/api/trainer/session").status_code == 200


def test_plus_keeps_more_books_and_a_lapsed_plus_keeps_them_all(paddle, outbox, monkeypatch):
    monkeypatch.setattr(config, "MAX_BOOKS", 1)
    monkeypatch.setattr(config, "PLUS_MAX_BOOKS", 3)
    monkeypatch.setattr(config, "PLUS_MAX_STORAGE_MB", 50)
    ana = signed_up(outbox)
    upload(ana, tiny_epub("1.e4 e5"), "one.epub")
    second = tiny_epub("1.d4 d5")
    assert ana.post("/api/books", data={"rights": "true"}, files={"file": ("two.epub", second)}).json()["detail"] == "books"

    user = plus(ana)
    usage = ana.get("/api/usage").json()
    assert usage["max_books"] == 3 and usage["max_bytes"] == 50 * 2**20
    upload(ana, second, "two.epub")
    kept = upload(ana, tiny_epub("1.c4 c5"), "three.epub")

    tell(subscription(user, status="canceled", at="2026-11-21T10:00:01.000000Z"))
    assert ana.get("/api/usage").json()["max_books"] == 1
    # Nothing is deleted: the books stay readable, and no new one fits until some are removed.
    assert len(ana.get("/api/books").json()) == 3
    assert ana.get(f"/api/books/{kept['id']}/analysis").status_code == 200
    refused = ana.post("/api/books", data={"rights": "true"}, files={"file": ("four.epub", tiny_epub("1.Nf3 Nf6"))})
    assert refused.json()["detail"] == "books"


def test_free_accounts_see_ads_where_the_site_shows_them(paddle, outbox, monkeypatch):
    ana = signed_up(outbox)
    assert ana.get("/api/plan").json()["ads"] is None
    assert browser().get("/ads.txt").status_code == 404

    monkeypatch.setattr(config, "ADS", True)
    monkeypatch.setattr(config, "ADSENSE_CLIENT", "ca-pub-1234567890")
    monkeypatch.setattr(config, "ADSENSE_SLOT", "9876")
    assert ana.get("/api/plan").json()["ads"] == {"client": "ca-pub-1234567890", "slot": "9876"}
    assert browser().get("/ads.txt").text == "google.com, pub-1234567890, DIRECT, f08c47fec0942fa0\n"
    assert browser().get("/api/plans").json()["ads"] is True

    plus(ana)
    assert ana.get("/api/plan").json()["ads"] is None


def test_deleting_an_account_ends_its_plus(paddle, outbox):
    ana = signed_up(outbox)
    plus(ana)
    assert ana.post("/api/auth/delete-account", json={"password": "wrong"}).status_code == 403
    assert paddle.calls == []

    # If Paddle can't be told, nothing is deleted: the reader would go on paying for nothing.
    paddle.answers["/subscriptions/sub_01/cancel"] = billing.Unavailable("HTTP Error 503")
    failed = ana.post("/api/auth/delete-account", json={"password": "correct horse"})
    assert failed.status_code == 502 and failed.json()["detail"] == "billing"
    assert ana.get("/api/plan").json()["plus"] is True

    del paddle.answers["/subscriptions/sub_01/cancel"]
    assert ana.post("/api/auth/delete-account", json={"password": "correct horse"}).status_code == 204
    assert paddle.calls[-1] == ("POST", "/subscriptions/sub_01/cancel", {"effective_from": "immediately"})
    with billing._db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


def test_closing_an_account_ends_its_plus(paddle, outbox):
    ana = signed_up(outbox)
    plus(ana)
    paddle.answers["/subscriptions/sub_01/cancel"] = billing.Unavailable("timed out")
    report = copyright.close("ana@example.com", "abuse of the service")
    assert report == ["ana@example.com: cancel their Plus subscription in Paddle's dashboard (Paddle said: timed out)"]

    bob = signed_up(outbox, "bob@example.com")
    plus_of_bob = bob.get("/api/plan").json()["checkout"]["user"]
    tell(subscription(plus_of_bob, sub="sub_02", kind="subscription.created"))
    assert copyright.close("bob@example.com", "abuse of the service") == []
    assert paddle.calls[-1] == ("POST", "/subscriptions/sub_02/cancel", {"effective_from": "immediately"})


def test_paddles_portal_manages_a_subscription(paddle, outbox):
    ana = signed_up(outbox)
    assert ana.post("/api/billing/portal").status_code == 404  # never bought Plus
    plus(ana)
    paddle.answers["/customers/ctm_01/portal-sessions"] = {"data": {"urls": {
        "general": {"overview": "https://customer-portal.paddle.com/cpl_01?action=overview&token=t"},
        "subscriptions": [{"id": "sub_01", "cancel_subscription": "https://customer-portal.paddle.com/cpl_01?action=cancel_subscription&token=t"}],
    }}}
    links = ana.post("/api/billing/portal").json()
    assert links["overview"].endswith("action=overview&token=t") and "cancel_subscription" in links["cancel"]
    assert paddle.calls[-1] == ("POST", "/customers/ctm_01/portal-sessions", {"subscription_ids": ["sub_01"]})

    paddle.answers["/customers/ctm_01/portal-sessions"] = billing.Unavailable("HTTP Error 500")
    assert ana.post("/api/billing/portal").json()["detail"] == "billing"


def test_the_plans_and_plus_price_are_public(paddle, outbox, monkeypatch):
    monkeypatch.setattr(config, "MAX_BOOKS", 3)
    monkeypatch.setattr(config, "PLUS_MAX_BOOKS", 300)
    paddle.answers["/prices/pri_plus"] = {"data": {"id": "pri_plus", "unit_price": {"amount": "500", "currency_code": "USD"},
                                                   "billing_cycle": {"interval": "month", "frequency": 1}, "trial_period": None}}
    plans = browser().get("/api/plans").json()
    assert plans["selling"] is True and plans["free"]["books"] == 3 and plans["free"]["trainer_sessions"] == 7
    assert plans["paddle"] == {"token": "test_token", "sandbox": True}
    assert plans["plus"]["books"] == 300
    assert plans["price"] == {"amount": "500", "currency": "USD", "interval": "month", "frequency": 1,
                              "trial_interval": None, "trial_frequency": None}
    browser().get("/api/plans")
    assert [c for c in paddle.calls if c[1] == "/prices/pri_plus"] == [("GET", "/prices/pri_plus", None)]  # asked once an hour

    monkeypatch.setattr(config, "SELLING", False)
    plans = browser().get("/api/plans").json()
    assert plans["price"] is None and plans["paddle"] is None and plans["free"]["trainer_sessions"] == 0


def test_the_local_app_has_no_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HOSTED", False)
    client = browser()
    assert client.get("/api/plan").status_code == 404
    assert client.get("/api/plans").status_code == 404
    assert client.post("/api/billing/webhook", content=b"{}").status_code == 404
    assert billing.limits(library.LOCAL) == (config.MAX_BOOKS, config.MAX_STORAGE_MB) == (0, 0)
    assert billing.trainer_left(library.LOCAL) is None
