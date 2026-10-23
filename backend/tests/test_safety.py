"""A hosted site's defences: what it takes in, how much each account keeps, how often anyone may
try things, and analyses that can't take the server down."""

import io
import os
import struct
import threading
import time
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient

from cbv import config, jobs, library, main, ratelimit
from cbv.ingest.pdf import MAX_PIXELS, render_page
from cbv.main import app
from cbv.ratelimit import Limit

from .test_accounts import SITE, browser, outbox, signed_up, wait_until_done  # noqa: F401 (outbox: a fixture)
from .test_copyright import BOOK, NOTICE, tiny_epub, upload
from .worker_jobs import dies, fails, grabs, sleeps


def pdf(width: float = 595, height: float = 842) -> bytes:
    doc = pymupdf.open()
    doc.new_page(width=width, height=height).insert_text((72, 72), "1.e4 e5 2.Nf3 Nc6")
    return doc.tobytes()


def post(client, name: str, data: bytes):
    return client.post("/api/books", data={"rights": "true"}, files={"file": (name, data)})


def elsewhere() -> TestClient:
    """A browser at another address."""
    return TestClient(app, base_url="https://testserver", client=("203.0.113.9", 50000))


def until(condition, seconds: float = 10) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "never happened"
        time.sleep(0.01)


# --- What a book upload may be ---

def test_a_book_is_what_its_file_holds_not_what_its_name_says(outbox, tmp_path):
    ana = signed_up(outbox)
    text = post(ana, "notes.pdf", b"just some notes")
    assert text.status_code == 415 and text.json()["detail"] == "format"
    some_zip = io.BytesIO()
    with zipfile.ZipFile(some_zip, "w") as z:
        z.writestr("photo.jpg", b"not a book")
    assert post(ana, "photos.epub", some_zip.getvalue()).json()["detail"] == "format"

    assert post(ana, "renamed.pdf", BOOK).json()["format"] == "epub"
    assert post(ana, "renamed.epub", pdf()).json()["format"] == "pdf"
    # What was refused isn't kept anywhere.
    assert list((tmp_path / "incoming").iterdir()) == []


def test_an_upload_past_the_size_limit_is_stopped(outbox, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    ana = signed_up(outbox)
    big = b"%PDF-1.4 " + bytes(2 * 2**20)
    refused = post(ana, "big.pdf", big)
    assert refused.status_code == 413 and refused.json()["detail"] == "too_big"

    # Sent in pieces, with no length said first: stopped as it arrives.
    boundary = "b0und4ry"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="rights"\r\n\r\ntrue\r\n--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="big.pdf"\r\n\r\n').encode() + big + f"\r\n--{boundary}--\r\n".encode()
    pieces = (body[i:i + 2**16] for i in range(0, len(body), 2**16))
    chunked = ana.post("/api/books", content=pieces, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert chunked.status_code == 413
    assert ana.get("/api/books").json() == []

    # And the library checks it again as it copies the file.
    with pytest.raises(library.Refused, match="too_big"):
        library.receive(io.BytesIO(big))
    assert list((tmp_path / "incoming").iterdir()) == []


def test_other_requests_are_small(outbox, monkeypatch):
    monkeypatch.setattr(main, "MAX_BODY", 1000)
    ana = signed_up(outbox)
    record = {"notes": "x" * 2000}
    assert ana.put("/api/trainer", json=record).status_code == 413
    pieces = (part for part in [b'{"notes": "', b"x" * 2000, b'"}'])
    assert ana.put("/api/trainer", content=pieces, headers={"Content-Type": "application/json"}).status_code == 413
    assert ana.put("/api/trainer", json={"notes": "short"}).status_code == 204


def test_an_epub_that_unpacks_to_too_much_is_refused(outbox, monkeypatch):
    monkeypatch.setattr(library, "EPUB_MAX_UNPACKED", 2**20)
    monkeypatch.setattr(library, "EPUB_MAX_FILES", 50)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", "<container/>")
        z.writestr("chapter.xhtml", bytes(2 * 2**20))
    assert len(bomb.getvalue()) < 10_000
    ana = signed_up(outbox)
    refused = post(ana, "bomb.epub", bomb.getvalue())
    assert refused.status_code == 413 and refused.json()["detail"] == "unpacked"

    crowd = io.BytesIO()
    with zipfile.ZipFile(crowd, "w") as z:
        z.writestr("META-INF/container.xml", "<container/>")
        for n in range(60):
            z.writestr(f"{n}.xhtml", "<p/>")
    assert post(ana, "crowd.epub", crowd.getvalue()).json()["detail"] == "unpacked"
    assert post(ana, "fine.epub", BOOK).status_code == 200


# --- How much an account keeps ---

def test_each_account_keeps_up_to_its_quota(outbox, monkeypatch):
    monkeypatch.setattr(config, "MAX_BOOKS", 2)
    monkeypatch.setattr(config, "MAX_STORAGE_MB", 1)
    ana = signed_up(outbox)
    one = upload(ana, tiny_epub("1.e4 e5"), "one.epub")
    upload(ana, tiny_epub("1.d4 d5"), "two.epub")
    full = post(ana, "three.epub", tiny_epub("1.c4 c5"))
    assert full.status_code == 403 and full.json()["detail"] == "books"
    # The same book again is the one already there.
    assert post(ana, "again.epub", tiny_epub("1.e4 e5")).json()["id"] == one["id"]
    usage = ana.get("/api/usage").json()
    assert usage["books"] == 2 and usage["max_books"] == 2 and usage["max_bytes"] == 2**20
    assert 0 < usage["bytes"] < 10_000

    ana.delete(f"/api/books/{one['id']}")
    heavy = post(ana, "heavy.pdf", b"%PDF-1.4 " + bytes(2**20))
    assert heavy.status_code == 403 and heavy.json()["detail"] == "storage"
    # Another account has its own room.
    bob = signed_up(outbox, "bob@example.com")
    assert post(bob, "three.epub", tiny_epub("1.c4 c5")).status_code == 200


def test_the_local_app_has_no_quota(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    client = TestClient(app)
    assert client.get("/api/usage").status_code == 404
    for n in range(3):
        assert client.post("/api/books", files={"file": (f"{n}.epub", tiny_epub(f"{n + 1}.e4 e5"))}).status_code == 200


# --- How often anyone may try ---

def test_tries_are_counted_per_network_and_forgotten_in_time(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    # Anyone with IPv6 has a whole /64 of addresses: it counts as one client.
    assert ratelimit.client("2001:db8:1:2::5") == ratelimit.client("2001:db8:1:2:ffff::9")
    assert ratelimit.client("2001:db8:1:2::5") != ratelimit.client("2001:db8:1:3::5")
    assert ratelimit.client("203.0.113.9") == "203.0.113.9"

    twice_a_minute = Limit(2, 60)
    t = time.monotonic()  # the clock the sweeper goes by
    ratelimit.take("try", "someone", twice_a_minute, now=t)
    ratelimit.take("try", "someone", twice_a_minute, now=t + 10)
    with pytest.raises(ratelimit.TooMany) as refused:
        ratelimit.take("try", "someone", twice_a_minute, now=t + 20)
    assert refused.value.retry_after == 41
    ratelimit.take("try", "someone else", twice_a_minute, now=t + 20)
    ratelimit.take("try", "someone", twice_a_minute, now=t + 61)  # the first try is a minute old


def test_who_tried_is_forgotten_within_the_hour(monkeypatch):
    # The privacy notice says addresses are kept in memory for an hour at most.
    monkeypatch.setattr(config, "HOSTED", True)
    t = time.monotonic()
    ratelimit.take("signup", "203.0.113.9", main.SIGNUPS, now=t)
    ratelimit.sweep(now=t + 3599)
    assert ("signup", "203.0.113.9") in ratelimit._tries
    ratelimit.sweep(now=t + 3600)
    assert ratelimit._tries == {}
    assert ratelimit._sweeper is not None and ratelimit._sweeper.is_alive()
    # No limit counts tries over a longer time than that.
    limits = [v for v in vars(main).values() if isinstance(v, Limit)]
    assert len(limits) >= 8 and all(limit.seconds <= ratelimit._LONGEST for limit in limits)


def login(client, email="ana@example.com", password="correct horse"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_password_guesses_are_slowed_down(outbox):
    signed_up(outbox)
    guesser = browser()
    for _ in range(10):
        assert login(guesser, password="wrong guess").status_code == 401
    slowed = login(guesser, password="wrong guess")
    assert slowed.status_code == 429 and slowed.json()["detail"] == "too_many"
    assert 0 < int(slowed.headers["retry-after"]) <= 900
    # The guesses are counted for the account, wherever they come from...
    assert login(elsewhere()).status_code == 429
    # ...and not for anyone else's.
    signed_up(outbox, "bob@example.com")
    assert login(elsewhere(), "bob@example.com").status_code == 204


def test_one_client_cant_sign_in_endlessly(outbox):
    client = browser()
    for n in range(20):
        assert login(client, f"nobody{n}@example.com").status_code == 401
    assert login(client, "nobody99@example.com").status_code == 429
    signed_up(outbox)
    assert login(elsewhere()).status_code == 204


def test_sign_ups_and_mails_are_limited(outbox):
    client = browser()
    for n in range(10):
        assert client.post("/api/auth/signup", json={"terms": True, "email": f"reader{n}@example.com", "password": "correct horse"}).status_code == 204
    assert client.post("/api/auth/signup", json={"terms": True, "email": "reader10@example.com", "password": "correct horse"}).status_code == 429
    # One address gets at most five mails an hour, whoever asks for them.
    for _ in range(4):
        assert elsewhere().post("/api/auth/forgot", json={"email": "reader0@example.com"}).status_code == 204
    assert elsewhere().post("/api/auth/forgot", json={"email": "reader0@example.com"}).status_code == 429
    assert elsewhere().post("/api/auth/resend", json={"email": "reader0@example.com"}).status_code == 429
    assert len([m for m in outbox if m["to"] == "reader0@example.com"]) == 5


def test_notices_and_uploads_are_limited(outbox, monkeypatch):
    for _ in range(5):
        assert browser().post("/api/copyright-notices", json=NOTICE).status_code == 201
    assert browser().post("/api/copyright-notices", json=NOTICE).status_code == 429
    assert elsewhere().post("/api/copyright-notices", json=NOTICE).status_code == 201

    monkeypatch.setattr(main, "UPLOADS", Limit(2, 3600))
    ana = signed_up(outbox)
    assert post(ana, "one.epub", tiny_epub("1.e4 e5")).status_code == 200
    assert post(ana, "two.epub", tiny_epub("1.d4 d5")).status_code == 200
    assert post(ana, "three.epub", tiny_epub("1.c4 c5")).status_code == 429


def test_the_local_app_limits_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "UPLOADS", Limit(1, 3600))
    client = TestClient(app)
    for n in range(3):
        assert client.post("/api/books", files={"file": (f"{n}.epub", tiny_epub(f"{n + 1}.d4 d5"))}).status_code == 200


# --- Analyses in worker processes ---

def test_a_job_past_its_time_is_stopped():
    said = []
    started = time.monotonic()
    with pytest.raises(jobs.Limit, match="time"):
        jobs.run(sleeps, 60, progress=said.append, minutes=0.02)
    assert said == [0.5] and time.monotonic() - started < 10


def test_a_job_past_its_memory_is_stopped():
    with pytest.raises(jobs.Limit, match="memory"):
        jobs.run(grabs, 8000, memory_mb=4000)
    assert jobs.run(grabs, 100, memory_mb=4000) == 100 * 2**20


def test_a_job_that_dies_or_fails_says_so():
    with pytest.raises(jobs.Crashed):
        jobs.run(dies)
    with pytest.raises(ValueError, match="not a chess book"):
        jobs.run(fails)


def test_a_book_that_takes_too_long_fails_alone(outbox, monkeypatch):
    monkeypatch.setattr(config, "ANALYSIS_MINUTES", 1e-6)
    ana = signed_up(outbox)
    slow = post(ana, "slow.epub", BOOK).json()
    done = wait_until_done(ana, slow["id"])
    assert done["status"] == "error" and done["error"] == "limit: time"
    monkeypatch.setattr(config, "ANALYSIS_MINUTES", 0)
    assert ana.post(f"/api/books/{slow['id']}/analyze").status_code == 202
    assert wait_until_done(ana, slow["id"])["status"] == "ready"


def test_readers_take_turns(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", True)
    monkeypatch.setattr(config, "WORKERS", 2)
    queue, started, finish = jobs.Queue(), [], threading.Event()

    def job(name):
        def work():
            started.append(name)
            finish.wait(5)
        return work

    for n in range(3):
        queue.submit("ana", ("ana", n), job(f"ana{n}"))
    queue.submit("ana", ("ana", 2), job("ana2 again"))
    # Ana's books go one at a time, though a worker is free...
    until(lambda: len(started) == 1)
    time.sleep(0.1)
    assert started == ["ana0"]
    # ...and Bob doesn't wait for them.
    queue.submit("bob", ("bob", 0), job("bob0"))
    until(lambda: len(started) == 2)
    assert started == ["ana0", "bob0"]
    finish.set()
    until(lambda: len(started) == 4)
    # The same book waiting twice went once.
    time.sleep(0.1)
    assert started == ["ana0", "bob0", "ana1", "ana2"]


def test_the_local_reader_has_both_workers(monkeypatch):
    monkeypatch.setattr(config, "HOSTED", False)
    monkeypatch.setattr(config, "WORKERS", 2)
    queue, started, finish = jobs.Queue(), [], threading.Event()
    for n in range(2):
        queue.submit("local", ("local", n), lambda n=n: (started.append(n), finish.wait(5)))
    until(lambda: len(started) == 2)
    finish.set()


# --- Page images ---

def test_a_huge_page_is_drawn_at_a_size_the_server_can_hold(tmp_path):
    path = tmp_path / "poster.pdf"
    path.write_bytes(pdf(14400, 14400))  # a page 5 m wide
    png = render_page(path, 0, 4.0)
    width, height = struct.unpack(">II", png[16:24])
    assert 4000 < width and width * height <= MAX_PIXELS


def test_page_images_are_kept_while_they_are_looked_at(outbox, tmp_path):
    ana = signed_up(outbox)
    book = upload(ana, pdf(), "one page.pdf")
    page = f"/api/books/{book['id']}/pages/0.png"
    # The hosted site draws pages only at the size the app shows them.
    assert ana.get(f"{page}?zoom=4").status_code == 422
    assert ana.get(page).status_code == 200
    [png] = tmp_path.glob("users/*/books/*/render/*.png")
    week_ago = time.time() - 8 * 86400
    os.utime(png, (week_ago, week_ago))
    assert library.forget_renders() == 1 and not png.exists()

    assert ana.get(page).status_code == 200
    os.utime(png, (week_ago, week_ago))
    assert ana.get(page).status_code == 200  # looked at again: kept another week
    assert library.forget_renders() == 0 and png.exists()
