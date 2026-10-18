import time

import pytest
from fastapi.testclient import TestClient

from cbv import library
from cbv.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "DATA_DIR", tmp_path)
    return TestClient(app)


def wait_until_done(client, book_id):
    for _ in range(100):
        meta = client.get(f"/api/books/{book_id}").json()
        if meta["status"] in ("ready", "error"):
            return meta
        time.sleep(0.02)
    raise AssertionError("analysis did not finish")


def test_upload_list_and_delete(client):
    meta = client.post("/api/books", files={"file": ("old.djvu", b"not a real book")}).json()
    assert meta["title"] == "old" and meta["format"] == "djvu"
    assert [b["id"] for b in client.get("/api/books").json()] == [meta["id"]]

    done = wait_until_done(client, meta["id"])
    assert done["status"] == "error" and done["error"].startswith("unsupported")
    assert client.get(f"/api/books/{meta['id']}/analysis").status_code == 404

    assert client.delete(f"/api/books/{meta['id']}").status_code == 204
    assert client.get("/api/books").json() == []


def test_same_file_is_imported_once(client):
    a = client.post("/api/books", files={"file": ("a.pdf", b"same bytes")}).json()
    b = client.post("/api/books", files={"file": ("b.pdf", b"same bytes")}).json()
    assert a["id"] == b["id"]
    wait_until_done(client, a["id"])


def test_bad_ids_are_404(client):
    assert client.get("/api/books/../../etc").status_code == 404
    assert client.get("/api/books/" + "0" * 40).status_code == 404


def epub_with_board_image() -> bytes:
    import io
    import zipfile

    import cv2

    from tests.test_vision import drawn_board

    img, _ = drawn_board()
    png = cv2.imencode(".png", img)[1].tobytes()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        z.writestr("content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><manifest>
<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="c1"/></spine></package>""")
        z.writestr("ch1.xhtml", """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><body>
<p>White to play.</p><div><img src="board.png"/></div><p>1.Rd8#</p></body></html>""")
        z.writestr("board.png", png)
    return buf.getvalue()


def test_correcting_a_diagram_reanalyses_with_the_fix(client):
    meta = client.post("/api/books", files={"file": ("puzzle.epub", epub_with_board_image())}).json()
    assert wait_until_done(client, meta["id"])["status"] == "ready"
    diagrams = client.get(f"/api/books/{meta['id']}/analysis").json()["diagrams"]
    assert len(diagrams) == 1 and diagrams[0]["key"] == "ch1.xhtml#board.png"

    fix = {"key": diagrams[0]["key"], "placement": "6k1/5ppp/8/8/8/8/5PPP/3R2K1", "turn": "w"}
    assert client.put(f"/api/books/{meta['id']}/diagrams", json=fix).status_code == 202
    assert wait_until_done(client, meta["id"])["status"] == "ready"
    analysis = client.get(f"/api/books/{meta['id']}/analysis").json()
    d = analysis["diagrams"][0]
    assert d["placement"] == fix["placement"] and d["corrected"] and d["node"]
    assert analysis["games"][0]["nodes"][1]["san"] == "Rd8#"

    bad = {**fix, "placement": "not a position"}
    assert client.put(f"/api/books/{meta['id']}/diagrams", json=bad).status_code == 422


def test_progress_and_annotations_are_kept_per_book(client):
    book = client.post("/api/books", files={"file": ("a.pdf", b"some bytes")}).json()["id"]
    assert client.get(f"/api/books/{book}/user/progress").json() == {}
    progress = {"problems": {"p3:40,300": {"result": "solved", "tries": 1, "hints": 0, "ms": 4200}}}
    assert client.put(f"/api/books/{book}/user/progress", json=progress).status_code == 204
    assert client.get(f"/api/books/{book}/user/progress").json() == progress
    arrows = {"8/8/8/8/8/8/8/K6k w": {"arrows": [["e2", "e4", "green"]], "circles": ["d5"]}}
    assert client.put(f"/api/books/{book}/user/annotations", json=arrows).status_code == 204
    assert client.get(f"/api/books/{book}/user/annotations").json() == arrows
    assert client.get(f"/api/books/{book}/user/secrets").status_code == 404
    assert client.put(f"/api/books/{book}/user/secrets", json={}).status_code == 404
    assert client.get(f"/api/books/{'0' * 40}/user/progress").status_code == 404


def test_move_fixes_are_checked_and_saved(client):
    book = client.post("/api/books", files={"file": ("a.pdf", b"other bytes")}).json()["id"]
    wait_until_done(client, book)
    assert client.get(f"/api/books/{book}/move-fixes").json() == []
    start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    fix = {"page": 0, "rect": [10, 10, 40, 22], "before": start, "uci": "e2e4"}
    assert client.put(f"/api/books/{book}/move-fixes", json=[fix]).status_code == 202
    assert client.get(f"/api/books/{book}/move-fixes").json() == [fix]
    illegal = {**fix, "uci": "e2e5"}
    assert client.put(f"/api/books/{book}/move-fixes", json=[illegal]).status_code == 422
    removal = {"page": 0, "rect": [10, 10, 40, 22], "remove": True}
    assert client.put(f"/api/books/{book}/move-fixes", json=[removal]).status_code == 202


def test_the_trainer_record_round_trips(client):
    record = client.get("/api/trainer").json()
    assert record["settings"]["minutes"] == 50 and record["sessions"] == []
    record["settings"]["focus"] = "endgames"
    record["sessions"].append({"id": "1", "focus": 7})
    assert client.put("/api/trainer", json=record).status_code == 204
    again = client.get("/api/trainer").json()
    assert again["settings"]["focus"] == "endgames" and again["sessions"] == [{"id": "1", "focus": 7}]
    assert client.post("/api/trainer/session").json()["blocks"] == []  # no books yet
    assert client.get("/api/trainer/books").json() == []
