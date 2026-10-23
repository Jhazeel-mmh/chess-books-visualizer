"""The hosted app: accounts, and each reader's library kept from everyone else."""

import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from cbv import config, copyright, library, mail, users
from cbv.main import app

SITE = "https://chess.example"


@pytest.fixture
def outbox(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "PUBLIC_URL", SITE)
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, kind, lang, reply_to=None, **fields: sent.append({"to": to, "kind": kind, "lang": lang, "reply_to": reply_to, **fields}))
    return sent


def browser() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def token(message: dict) -> str:
    return parse_qs(urlsplit(message["link"]).query)["token"][0]


def signed_up(outbox, email="ana@example.com", password="correct horse") -> TestClient:
    client = browser()
    assert client.post("/api/auth/signup", json={"terms": True, "email": email, "password": password, "lang": "es"}).status_code == 204
    assert client.post("/api/auth/verify", json={"token": token(outbox[-1])}).status_code == 204
    return client


def wait_until_done(client, book_id):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        meta = client.get(f"/api/books/{book_id}").json()
        if meta["status"] in ("ready", "error"):
            return meta
        time.sleep(0.02)
    raise AssertionError("analysis did not finish")


def test_an_account_starts_once_its_email_is_confirmed(outbox):
    client = browser()
    assert client.get("/api/auth/me").json() == {"hosted": True, "user": None}
    assert client.post("/api/auth/signup", json={"terms": True, "email": " Ana@Example.com ", "password": "correct horse", "lang": "es"}).status_code == 204
    [message] = outbox
    assert message["to"] == "ana@example.com" and message["kind"] == "verify" and message["lang"] == "es"
    assert message["link"].startswith(f"{SITE}/verify?token=")

    refused = client.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"})
    assert refused.status_code == 403 and refused.json()["detail"] == "unverified"

    confirmed = client.post("/api/auth/verify", json={"token": token(message)})
    assert confirmed.status_code == 204
    cookie = confirmed.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    assert client.get("/api/auth/me").json() == {"hosted": True, "user": {"email": "ana@example.com"}}
    # A confirmation link works once.
    assert client.post("/api/auth/verify", json={"token": token(message)}).json()["detail"] == "link"


def test_signing_up_accepts_the_terms(outbox):
    refused = browser().post("/api/auth/signup", json={"email": "ana@example.com", "password": "correct horse", "lang": "es"})
    assert refused.status_code == 400 and refused.json()["detail"] == "terms"
    assert outbox == []


def test_an_email_nobody_confirms_is_forgotten_after_a_week(outbox):
    signed_up(outbox, "bob@example.com")
    assert browser().post("/api/auth/signup", json={"terms": True, "email": "ana@example.com", "password": "correct horse"}).status_code == 204
    a_week_ago = (datetime.now(timezone.utc) - timedelta(days=users.UNVERIFIED_DAYS, minutes=1)).isoformat()
    with users.connect() as conn:
        conn.execute("UPDATE users SET created_at = ?", (a_week_ago,))
    users.tidy()
    with users.connect() as conn:
        assert [r["email"] for r in conn.execute("SELECT email FROM users")] == ["bob@example.com"]
    # Signing up again starts over, instead of saying the account exists.
    assert browser().post("/api/auth/signup", json={"terms": True, "email": "ana@example.com", "password": "correct horse"}).status_code == 204
    assert outbox[-1]["kind"] == "verify"


def test_the_legal_pages_name_who_runs_the_site(outbox, monkeypatch):
    monkeypatch.setattr(config, "OPERATOR", "Ana Reader")
    monkeypatch.setattr(config, "CONTACT_EMAIL", "privacy@chess.example")
    legal = browser().get("/api/legal").json()
    assert legal["operator"] == "Ana Reader" and legal["contact"] == "privacy@chess.example" and legal["site"] == SITE
    assert legal["address"] is None  # unset: the pages show a blank
    assert legal["strikes"] == copyright.STRIKES and legal["wait_days"] == copyright.WAIT_DAYS == 15
    assert legal["session_days"] == users.SESSION_DAYS and legal["unverified_days"] == users.UNVERIFIED_DAYS
    monkeypatch.setattr(config, "HOSTED", False)
    assert browser().get("/api/legal").status_code == 404


def test_bad_emails_and_short_passwords_are_refused(outbox):
    client = browser()
    assert client.post("/api/auth/signup", json={"terms": True, "email": "not an email", "password": "correct horse"}).json()["detail"] == "email"
    assert client.post("/api/auth/signup", json={"terms": True, "email": "ana@example.com", "password": "short"}).json()["detail"] == "password"
    assert outbox == []


def test_nothing_tells_whether_an_email_has_an_account(outbox):
    signed_up(outbox)
    again = browser().post("/api/auth/signup", json={"terms": True, "email": "ana@example.com", "password": "another one", "lang": "en"})
    assert again.status_code == 204
    # The owner is told instead, in the language of the account.
    assert outbox[-1]["kind"] == "exists" and outbox[-1]["lang"] == "es"

    wrong_password = browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "wrong password"})
    no_account = browser().post("/api/auth/login", json={"email": "bob@example.com", "password": "wrong password"})
    assert wrong_password.status_code == no_account.status_code == 401
    assert wrong_password.json() == no_account.json()

    before = len(outbox)
    assert browser().post("/api/auth/forgot", json={"email": "bob@example.com"}).status_code == 204
    assert len(outbox) == before


def test_each_reader_sees_only_their_own_books(outbox):
    ana = signed_up(outbox, "ana@example.com")
    bob = signed_up(outbox, "bob@example.com")
    book = ana.post("/api/books", data={"rights": "true"}, files={"file": ("mine.pdf", b"%PDF-1.4 ana's book")}).json()
    wait_until_done(ana, book["id"])
    b = f"/api/books/{book['id']}"

    assert bob.get("/api/books").json() == []
    for method, url, body in [
        ("get", b, None), ("delete", b, None), ("post", f"{b}/analyze", None), ("get", f"{b}/analysis", None),
        ("get", f"{b}/layout", None), ("get", f"{b}/pages/0.png", None), ("get", f"{b}/pages/0/marks", None),
        ("get", f"{b}/epub/text.html", None), ("put", f"{b}/diagrams", {"key": "k", "placement": "8/8/8/8/8/8/8/8"}),
        ("get", f"{b}/move-fixes", None), ("put", f"{b}/move-fixes", []), ("get", f"{b}/user/progress", None),
        ("put", f"{b}/user/progress", {}), ("get", f"{b}/games/g1.pgn", None),
        ("post", f"{b}/counter-notice", {"name": "Bob", "address": "Somewhere", "phone": "1", "signature": "Bob",
                                         "good_faith": True, "jurisdiction": True}),
    ]:
        response = getattr(bob, method)(url, **({"json": body} if body is not None else {}))
        assert response.status_code == 404, (method, url, response.status_code)
    assert [m["id"] for m in ana.get("/api/books").json()] == [book["id"]]

    # The same file imported by both is two books, one in each library.
    copy = bob.post("/api/books", data={"rights": "true"}, files={"file": ("mine.pdf", b"%PDF-1.4 ana's book")}).json()
    wait_until_done(bob, copy["id"])
    bob.delete(f"/api/books/{copy['id']}")
    assert ana.get(b).status_code == 200


def test_each_reader_has_their_own_training_record(outbox):
    ana = signed_up(outbox, "ana@example.com")
    bob = signed_up(outbox, "bob@example.com")
    record = ana.get("/api/trainer").json()
    record["settings"]["rating"] = 2100
    assert ana.put("/api/trainer", json=record).status_code == 204
    assert ana.get("/api/trainer").json()["settings"]["rating"] == 2100
    assert bob.get("/api/trainer").json()["settings"]["rating"] != 2100


def test_without_a_session_only_public_routes_answer(outbox):
    stranger = browser()
    for url in ["/api/books", "/api/trainer", "/api/trainer/books"]:
        assert stranger.get(url).status_code == 401
    assert stranger.post("/api/books", data={"rights": "true"}, files={"file": ("a.pdf", b"x")}).status_code == 401
    for url in ["/api/health", "/api/licenses", "/api/auth/me"]:
        assert stranger.get(url).status_code == 200


def test_signing_out_ends_the_session(outbox):
    ana = signed_up(outbox)
    assert ana.get("/api/books").status_code == 200
    assert ana.post("/api/auth/logout").status_code == 204
    assert ana.get("/api/books").status_code == 401
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 204


def test_a_new_password_ends_every_session(outbox):
    old = signed_up(outbox)
    stranger = browser()
    assert stranger.post("/api/auth/forgot", json={"email": "ana@example.com"}).status_code == 204
    assert outbox[-1]["kind"] == "reset" and outbox[-1]["link"].startswith(f"{SITE}/reset?token=")
    link = token(outbox[-1])
    assert stranger.post("/api/auth/reset", json={"token": link, "password": "short"}).json()["detail"] == "password"
    assert stranger.post("/api/auth/reset", json={"token": link, "password": "battery staple"}).status_code == 204

    assert old.get("/api/books").status_code == 401
    assert stranger.get("/api/books").status_code == 200
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 401
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "battery staple"}).status_code == 204
    assert browser().post("/api/auth/reset", json={"token": link, "password": "another one"}).json()["detail"] == "link"


def test_closing_an_account_deletes_its_library(outbox, tmp_path):
    ana = signed_up(outbox)
    book = ana.post("/api/books", data={"rights": "true"}, files={"file": ("mine.pdf", b"%PDF-1.4 ana's book")}).json()
    wait_until_done(ana, book["id"])
    [library_dir] = (tmp_path / "users").iterdir()
    assert (library_dir / "books" / book["id"]).is_dir()

    assert ana.post("/api/auth/delete-account", json={"password": "wrong password"}).status_code == 403
    assert ana.post("/api/auth/delete-account", json={"password": "correct horse"}).status_code == 204
    assert not library_dir.exists()
    assert ana.get("/api/books").status_code == 401
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 401


def test_requests_from_other_sites_are_refused(outbox):
    ana = signed_up(outbox)
    forged = ana.post("/api/books", data={"rights": "true"}, files={"file": ("a.pdf", b"x")}, headers={"Origin": "https://evil.example"})
    assert forged.status_code == 403
    assert ana.post("/api/auth/logout", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert ana.get("/api/books").status_code == 200  # still signed in
    assert ana.post("/api/auth/logout", headers={"Origin": SITE}).status_code == 204


def test_the_local_app_has_no_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    client = TestClient(app)
    assert client.get("/api/auth/me").json() == {"hosted": False, "user": None}
    assert client.post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 404
    assert client.get("/api/books").status_code == 200
