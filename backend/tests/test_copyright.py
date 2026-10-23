"""The hosted app's copyright process: notices, takedowns, counter-notices, strikes."""

import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from cbv import config, copyright, library, users
from cbv.main import app

from .test_accounts import SITE, browser, outbox, signed_up, wait_until_done  # noqa: F401 (outbox: a fixture)

AGENT = "copyright@chess.example"
ROOT = Path(__file__).resolve().parents[2]


def tiny_epub(moves: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        z.writestr("content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><manifest>
<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>""")
        z.writestr("ch1.xhtml", f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Game</h1><p><b>{moves}</b></p></body></html>""")
    return buf.getvalue()


BOOK = tiny_epub("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6")


def upload(client, data=BOOK, name="Ajedrez Táctico.epub") -> dict:
    response = client.post("/api/books", data={"rights": "true"}, files={"file": (name, data)})
    assert response.status_code == 200, response.text
    meta = response.json()
    wait_until_done(client, meta["id"])
    return meta


def account(email="ana@example.com") -> str:
    return users.find(email).id


NOTICE = {
    "name": "Rita Agent", "email": "rita@publisher.example", "phone": "+1 555 0100", "address": "1 Book St, Springfield",
    "claimant": "Example Chess Publishing", "work": "Ajedrez Táctico, by A. Author (ISBN 978-0-00-000000-0)",
    "location": "", "signature": "Rita Agent", "good_faith": True, "accurate": True, "lang": "es",
}

COUNTER = {
    "name": "Ana Reader", "address": "Calle 1, CDMX", "phone": "+52 55 0000 0000", "reason": "I bought this ebook.",
    "signature": "Ana Reader", "good_faith": True, "jurisdiction": True, "lang": "es",
}


def notice(**changes) -> int:
    response = browser().post("/api/copyright-notices", json={**NOTICE, **changes})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_the_forms_show_the_statements_that_are_kept():
    for lang in ("en", "es"):
        texts = json.loads((ROOT / "frontend" / "src" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))["copyright"]
        assert [texts["goodFaith"], texts["accurate"]] == copyright.STATEMENTS["notice"][lang]
        assert [texts["counterGoodFaith"], texts["jurisdiction"]] == copyright.STATEMENTS["counter"][lang]
        assert "{{days}}" in texts["counterIntro"]  # the wait, from /api/legal


def test_the_wait_skips_weekends_and_mexican_holidays():
    friday = datetime(2026, 11, 13, tzinfo=timezone.utc)
    assert copyright._business_days(friday, friday + timedelta(days=4)) == 1  # Monday the 16th: Revolution Day
    new_year = datetime(2026, 12, 31, tzinfo=timezone.utc)
    assert copyright._business_days(new_year, new_year + timedelta(days=1)) == 0
    # The first Monday of February 2027 (Constitution Day), and a president's inauguration in 2030.
    assert copyright._holiday(date(2027, 2, 1)) and not copyright._holiday(date(2027, 2, 8))
    assert copyright._holiday(date(2030, 10, 1)) and not copyright._holiday(date(2026, 10, 1))


def test_uploading_to_the_site_needs_the_declaration(outbox):
    ana = signed_up(outbox)
    refused = ana.post("/api/books", files={"file": ("mine.epub", BOOK)})
    assert refused.status_code == 400 and refused.json()["detail"] == "rights"
    assert ana.get("/api/books").json() == []

    meta = upload(ana)
    assert meta["declared_at"] and meta["sha256"] == hashlib.sha256(BOOK).hexdigest()


def test_the_local_app_asks_for_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    client = TestClient(app)
    meta = client.post("/api/books", files={"file": ("mine.epub", BOOK)}).json()
    assert "declared_at" not in meta
    wait_until_done(client, meta["id"])
    assert client.post("/api/copyright-notices", json=NOTICE).status_code == 404


def test_anyone_can_send_a_notice_and_it_reaches_the_agent(outbox, monkeypatch):
    monkeypatch.setattr(config, "COPYRIGHT_EMAIL", AGENT)
    stranger = browser()
    assert stranger.post("/api/copyright-notices", json={**NOTICE, "accurate": False}).status_code == 422
    assert stranger.post("/api/copyright-notices", json={**NOTICE, "work": "  "}).status_code == 422
    assert stranger.post("/api/copyright-notices", json={**NOTICE, "email": "rita"}).status_code == 422
    assert outbox == []

    number = notice(sha256=hashlib.sha256(BOOK).hexdigest())
    [message] = outbox
    assert message["to"] == AGENT and message["kind"] == "notice" and message["id"] == number
    assert message["reply_to"] == NOTICE["email"]
    # The agent sees all of it, the statements in the words they were made in.
    assert NOTICE["work"] in message["text"] and copyright.STATEMENTS["notice"]["es"][1] in message["text"]
    assert [n["id"] for n in copyright.notices()] == [number]


def test_whoever_sent_a_notice_that_wont_be_acted_on_is_told_why(outbox, monkeypatch):
    monkeypatch.setattr(config, "COPYRIGHT_EMAIL", AGENT)
    number = notice()
    copyright.reject(number, "no book of this title was uploaded here.")
    message = outbox[-1]
    assert message["to"] == NOTICE["email"] and message["kind"] == "rejected" and message["lang"] == NOTICE["lang"]
    assert message["why"] == "no book of this title was uploaded here." and message["link"] == f"{SITE}/copyright"
    assert message["reply_to"] == AGENT and copyright.notice(number)["status"] == "rejected"


def test_a_notice_takes_down_the_copies_it_names(outbox):
    ana, bob = signed_up(outbox, "ana@example.com"), signed_up(outbox, "bob@example.com")
    book = upload(ana)
    upload(bob)  # the same file
    other = upload(ana, tiny_epub("1.d4 d5 2.c4"), "Otro libro.epub")
    number = notice(sha256=book["sha256"])

    # By the file's fingerprint, or the title's words (case and accents aside).
    found = copyright.find(sha256=book["sha256"])
    assert sorted(u.email for u in found) == ["ana@example.com", "bob@example.com"]
    assert [u.email for u in copyright.find(title="ajedrez tactico")] == ["ana@example.com", "bob@example.com"]
    assert all(u.declared_at for u in found)

    report = copyright.disable(number, [(account(), book["id"])])
    assert report == [f"ana@example.com: “Ajedrez Táctico” disabled (takedown #1); strike 1 of {copyright.STRIKES}"]
    b = f"/api/books/{book['id']}"
    for method, url in [("get", f"{b}/analysis"), ("get", f"{b}/layout"), ("get", f"{b}/epub/ch1.xhtml"),
                        ("get", f"{b}/games/g1.pgn"), ("post", f"{b}/analyze"), ("get", f"{b}/move-fixes"),
                        ("get", f"{b}/pages/0/marks")]:
        response = getattr(ana, method)(url)
        assert response.status_code == 451 and response.json()["detail"] == "disabled", (method, url)
    # The owner still sees it listed, with why, and can delete it.
    meta = ana.get(b).json()
    assert meta["disabled"]["claimant"] == NOTICE["claimant"] and meta["disabled"]["work"] == NOTICE["work"]
    assert [m.get("disabled") is not None for m in ana.get("/api/books").json()] == [False, True]
    assert [t["id"] for t in ana.get("/api/trainer/books").json()] == [other["id"]]
    # Only the copy named was disabled.
    assert bob.get(f"{b}/analysis").status_code == 200

    message = outbox[-1]
    assert message["to"] == "ana@example.com" and message["kind"] == "takedown" and message["lang"] == "es"
    assert message["strikes"] == 1 and message["claimant"] == NOTICE["claimant"]
    assert message["link"] == f"{SITE}/copyright/counter/{book['id']}"
    assert copyright.notice(number)["status"] == "done"


def test_a_blocked_file_cant_be_uploaded_again(outbox):
    ana, carol = signed_up(outbox, "ana@example.com"), signed_up(outbox, "carol@example.com")
    number = notice()
    copyright.block(hashlib.sha256(BOOK).hexdigest(), number)
    for client in (ana, carol):
        refused = client.post("/api/books", data={"rights": "true"}, files={"file": ("renamed.epub", BOOK)})
        assert refused.status_code == 451 and refused.json()["detail"] == "blocked"
    assert upload(ana, tiny_epub("1.c4"))["status"] == "queued"

    copyright.unblock(hashlib.sha256(BOOK).hexdigest())
    upload(carol)


def test_a_counter_notice_brings_the_book_back(outbox, monkeypatch):
    monkeypatch.setattr(config, "COPYRIGHT_EMAIL", AGENT)
    ana, bob = signed_up(outbox, "ana@example.com"), signed_up(outbox, "bob@example.com")
    book = upload(ana)
    b = f"/api/books/{book['id']}"
    assert ana.post(f"{b}/counter-notice", json=COUNTER).json()["detail"] == "not_disabled"
    number = notice()
    copyright.disable(number, [(account(), book["id"])])

    assert bob.post(f"{b}/counter-notice", json=COUNTER).status_code == 404
    assert ana.post(f"{b}/counter-notice", json={**COUNTER, "jurisdiction": False}).status_code == 422
    assert ana.post(f"{b}/counter-notice", json=COUNTER).status_code == 204
    assert ana.post(f"{b}/counter-notice", json=COUNTER).json()["detail"] == "sent"
    assert ana.get(b).json()["disabled"]["counter_at"]
    [counter] = copyright.counters()
    assert outbox[-1]["to"] == AGENT and outbox[-1]["kind"] == "counter" and outbox[-1]["id"] == counter["id"]

    # The book comes back only after the counter-notice went to whoever sent the notice, and they had time to go to court.
    takedown = counter["takedown_id"]
    try:
        copyright.restore(takedown)
        raise AssertionError("restored before forwarding")
    except copyright.Refused as e:
        assert "forward" in e.why
    forwarded = datetime(2026, 10, 19, tzinfo=timezone.utc)  # a Monday
    assert copyright.forward(counter["id"], now=forwarded) == NOTICE["email"]
    message = outbox[-1]
    assert message["kind"] == "forwarded" and message["lang"] == "es" and message["wait"] == copyright.WAIT_DAYS
    assert COUNTER["address"] in message["text"] and copyright.STATEMENTS["counter"]["es"][1] in message["text"]
    try:
        copyright.restore(takedown, now=forwarded + timedelta(days=20))  # fourteen business days
        raise AssertionError("restored too soon")
    except copyright.Refused as e:
        assert "business days" in e.why

    assert copyright.restore(takedown, now=forwarded + timedelta(days=21)) == ["ana@example.com: “Ajedrez Táctico” restored"]
    assert ana.get(f"{b}/analysis").status_code == 200 and "disabled" not in ana.get(b).json()
    assert copyright.strikes("ana@example.com") == 0
    assert outbox[-1]["kind"] == "restored" and outbox[-1]["to"] == "ana@example.com"


def test_three_strikes_close_the_account(outbox):
    ana = signed_up(outbox)
    books = [upload(ana, tiny_epub(f"1.e4 e5 2.Nf3 {i}..."), f"Book {i}.epub") for i in range(3)]
    takedowns = []
    for i, book in enumerate(books):
        report = copyright.disable(notice(work=f"Book {i}"), [(account(), book["id"])])
        takedowns.append(copyright.takedowns("ana@example.com")[-1]["id"])
    assert report[-1] == "ana@example.com: account closed (3 strikes)"
    assert [m["kind"] for m in outbox[-2:]] == ["takedown", "closed"]

    assert ana.get("/api/books").status_code == 401
    login = browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"})
    assert login.status_code == 403 and login.json()["detail"] == "closed"
    # Its email can't start again, and nothing says so.
    sent = len(outbox)
    assert browser().post("/api/auth/signup", json={"terms": True, "email": "ana@example.com", "password": "another one"}).status_code == 204
    assert browser().post("/api/auth/forgot", json={"email": "ana@example.com"}).status_code == 204
    assert len(outbox) == sent

    # A strike withdrawn (the notice was a mistake) opens it again.
    assert copyright.restore(takedowns[0], force=True)[-1] == "ana@example.com: account open again"
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 204


def test_strikes_follow_the_email_to_a_new_account(outbox):
    ana = signed_up(outbox)
    copyright.disable(notice(), [(account(), upload(ana)["id"])])
    assert ana.post("/api/auth/delete-account", json={"password": "correct horse"}).status_code == 204

    again = signed_up(outbox)
    copyright.disable(notice(work="Another book"), [(account(), upload(again, tiny_epub("1.d4"))["id"])])
    assert outbox[-1]["kind"] == "takedown" and outbox[-1]["strikes"] == 2


def test_what_nobody_answered_for_is_deleted_later(outbox):
    ana = signed_up(outbox)
    quiet, answered = upload(ana), upload(ana, tiny_epub("1.d4"), "Answered.epub")
    copyright.disable(notice(), [(account(), quiet["id"]), (account(), answered["id"])])
    assert ana.post(f"/api/books/{answered['id']}/counter-notice", json=COUNTER).status_code == 204

    assert copyright.purge() == []
    later = datetime.now(timezone.utc) + timedelta(days=copyright.KEEP_DAYS + 1)
    assert copyright.purge(now=later) == ["ana@example.com: deleted “Ajedrez Táctico” (takedown #1)"]
    assert [m["id"] for m in ana.get("/api/books").json()] == [answered["id"]]

    copyright.close("ana@example.com", "abuse of the service")
    assert outbox[-1]["kind"] == "closed_other" and outbox[-1]["reason"] == "abuse of the service"
    library_dir = library.user_dir(account())
    assert library_dir.is_dir()
    later = datetime.now(timezone.utc) + timedelta(days=copyright.KEEP_DAYS + 1)
    assert copyright.purge(now=later) == ["ana@example.com: deleted the library of the closed account"]
    assert not library_dir.exists()
    assert users.closed(account())  # the email stays, closed
    assert browser().post("/api/auth/login", json={"email": "ana@example.com", "password": "correct horse"}).status_code == 401


def test_the_admin_tool(outbox, tmp_path):
    ana = signed_up(outbox)
    book = upload(ana)
    number = notice(sha256=book["sha256"])

    def admin(*args):
        env = {**os.environ, "CBV_DATA_DIR": str(tmp_path), "CBV_PUBLIC_URL": SITE}
        env.pop("CBV_SMTP_HOST", None)
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "admin.py"), *args], env=env, capture_output=True, text=True)
        return run.returncode, run.stdout + run.stderr

    code, out = admin("notices")
    assert code == 0 and f"#{number}" in out and "[has a fingerprint]" in out
    code, out = admin("find", "--notice", str(number))
    assert code == 0 and book["id"] in out and "ana@example.com" in out and "declared" in out
    code, out = admin("disable", str(number), book["id"])
    assert code == 0 and "disabled (takedown #1); strike 1 of 3" in out
    assert "A book in your library was disabled" in out or "Se deshabilitó un libro" in out  # the mail, logged
    assert ana.get(f"/api/books/{book['id']}/analysis").status_code == 451
    code, out = admin("account", "ana@example.com")
    assert code == 0 and "DISABLED" in out and "Strikes: 1 of 3" in out
    code, out = admin("restore", "99")
    assert code == 1 and "no takedown #99" in out
