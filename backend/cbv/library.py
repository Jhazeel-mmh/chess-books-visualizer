"""Book storage: one folder per book under the data directory.

    <data>/books/<sha1>/book.<ext>      the original file
                        meta.json       title, format, analysis status
                        analysis.json   games, unresolved fragments, diagrams, stats
                        layout.json     how to show the book: EPUB chapters or PDF pages
                        pgn.json        PGN text per game id
                        epub/…          EPUB chapters with the moves wrapped in spans
                        pages/<n>.json  PDF: highlight boxes per page
                        render/…        PDF: cached page images
                        vision.json     diagrams already read from images (cache)
                        corrections.json  diagram positions fixed by the reader
                        progress.json   solving: results per problem and training cycles
                        annotations.json  the reader's arrows and circles per position
                        move_fixes.json  moves the reader entered on the pages (or false ones removed)
                        glyphs.npz  scans: figurine shapes cropped from the pages (rebuilt if lost)
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import re
import shutil
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import ingest, trainer
from .parse import analyze
from .vision import figurines

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("CBV_DATA_DIR", "~/.local/share/chess-books-visualizer")).expanduser()
_ID = re.compile(r"^[0-9a-f]{40}$")
_executor = ThreadPoolExecutor(max_workers=2)
_lock = threading.Lock()


class NotFound(Exception):
    pass


def books_dir() -> Path:
    return DATA_DIR / "books"


def book_dir(book_id: str) -> Path:
    if not _ID.match(book_id):
        raise NotFound(book_id)
    d = books_dir() / book_id
    if not d.is_dir():
        raise NotFound(book_id)
    return d


def list_books() -> list[dict]:
    if not books_dir().is_dir():
        return []
    metas = [_read_json(d / "meta.json") for d in books_dir().iterdir() if (d / "meta.json").is_file()]
    return sorted(metas, key=lambda m: m["imported_at"], reverse=True)


def get_book(book_id: str) -> dict:
    return _read_json(book_dir(book_id) / "meta.json")


def import_book(filename: str, data: bytes) -> dict:
    book_id = hashlib.sha1(data).hexdigest()
    d = books_dir() / book_id
    if (d / "meta.json").is_file():
        return get_book(book_id)
    suffix = Path(filename).suffix.lower()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"book{suffix}").write_bytes(data)
    meta = {
        "id": book_id,
        "title": Path(filename).stem,
        "filename": filename,
        "format": suffix.lstrip("."),
        "status": "queued",
        "error": None,
        "stats": None,
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(d / "meta.json", meta)
    start_analysis(book_id)
    return meta


def resume_unfinished() -> None:
    """Restarts analyses that were cut short (the server stopped while they ran)."""
    for meta in list_books():
        if meta["status"] in ("queued", "analyzing"):
            start_analysis(meta["id"])


def delete_book(book_id: str) -> None:
    shutil.rmtree(book_dir(book_id))


def start_analysis(book_id: str) -> None:
    _update_meta(book_id, status="queued", error=None, progress=None)
    _executor.submit(_analyze, book_id)


def analysis(book_id: str) -> dict:
    path = book_dir(book_id) / "analysis.json"
    if not path.is_file():
        raise NotFound(book_id)
    return _read_json(path)


def layout(book_id: str) -> dict:
    path = book_dir(book_id) / "layout.json"
    if not path.is_file():
        raise NotFound(book_id)
    return _read_json(path)


def page_marks(book_id: str, page: int) -> list:
    path = book_dir(book_id) / "pages" / f"{page}.json"
    return _read_json(path) if path.is_file() else []


def page_image(book_id: str, page: int, zoom: float) -> Path:
    """PNG of a PDF page, rendered once and cached."""
    from .ingest.pdf import render_page

    d = book_dir(book_id)
    pages = len(layout(book_id).get("pages", []))
    if not 0 <= page < pages:
        raise NotFound(str(page))
    cached = d / "render" / f"{page}@{zoom:g}.png"
    if not cached.is_file():
        cached.parent.mkdir(exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        tmp.write_bytes(render_page(d / "book.pdf", page, zoom))
        tmp.replace(cached)
    return cached


def epub_file(book_id: str, path: str) -> tuple[bytes, str]:
    """A chapter (annotated) or resource of an EPUB book."""
    d = book_dir(book_id)
    if not (d / "book.epub").is_file():
        raise NotFound(path)
    annotated = (d / "epub" / path).resolve()
    if (d / "epub").resolve() in annotated.parents and annotated.is_file():
        data = annotated.read_bytes()
    else:
        with zipfile.ZipFile(d / "book.epub") as z:
            if path not in z.namelist() or path.lower().endswith((".html", ".xhtml", ".htm")):
                raise NotFound(path)
            data = z.read(path)
    if path.lower().endswith((".html", ".xhtml", ".htm")):
        return data, "application/xhtml+xml"
    return data, mimetypes.guess_type(path)[0] or "application/octet-stream"


def correct_diagram(book_id: str, key: str, fen_placement: str, turn: str | None) -> dict:
    """Saves the reader's fix of a diagram's position and re-analyses the book with it."""
    import chess

    d = book_dir(book_id)
    chess.Board(f"{fen_placement} w - - 0 1")  # raises ValueError if the placement is malformed
    with _lock:
        corrections = _corrections(d)
        corrections[key] = {"placement": fen_placement, "turn": turn}
        _write_json(d / "corrections.json", corrections)
    start_analysis(book_id)
    return get_book(book_id)


def _corrections(d: Path) -> dict:
    path = d / "corrections.json"
    return _read_json(path) if path.is_file() else {}


# What the reader saves for a book: kept apart from the analysis, which may be rebuilt at any time.
USER_DATA = {"progress", "annotations"}
USER_DATA_LIMIT = 5_000_000  # bytes of JSON per file


def user_data(book_id: str, name: str) -> dict:
    path = book_dir(book_id) / f"{name}.json"
    return _read_json(path) if path.is_file() else {}


def save_user_data(book_id: str, name: str, data: dict) -> None:
    if name not in USER_DATA:
        raise NotFound(name)
    if len(json.dumps(data)) > USER_DATA_LIMIT:
        raise ValueError(f"{name} is too large")
    with _lock:
        _write_json(book_dir(book_id) / f"{name}.json", data)


def move_fixes(book_id: str) -> list[dict]:
    path = book_dir(book_id) / "move_fixes.json"
    return _read_json(path) if path.is_file() else []


def save_move_fixes(book_id: str, fixes: list[dict]) -> dict:
    """Saves the reader's move fixes (all of them) and analyses the book again with them."""
    import chess

    for fix in fixes:
        if not isinstance(fix.get("page"), int) or len(fix.get("rect") or []) != 4:
            raise ValueError("a fix needs a page and a rect")
        if not fix.get("remove"):
            board = chess.Board(fix.get("before") or "")  # raises ValueError if the FEN is malformed
            if chess.Move.from_uci(fix.get("uci") or "0000") not in board.legal_moves:
                raise ValueError(f"{fix.get('uci')} is not legal in {fix.get('before')}")
    d = book_dir(book_id)
    with _lock:
        _write_json(d / "move_fixes.json", fixes)
    start_analysis(book_id)
    return get_book(book_id)


def game_pgn(book_id: str, game_id: str) -> str:
    pgns = _read_json(book_dir(book_id) / "pgn.json")
    if game_id not in pgns:
        raise NotFound(game_id)
    return pgns[game_id]


def _analyze(book_id: str) -> None:
    d = book_dir(book_id)
    _update_meta(book_id, status="analyzing")
    try:
        source = next(d.glob("book.*"))
        book = ingest.open_book(source, cache=d / "vision.json", progress=lambda f: _update_meta(book_id, progress=round(f, 2)))
        fixes = move_fixes(book_id)
        if fixes and hasattr(book, "place_fixes"):
            book.place_fixes(fixes)
        corrections = _corrections(d)
        for block in book.doc.blocks:
            fix = corrections.get(block.key) if block.kind == "diagram" else None
            if fix:
                block.placement, block.turn = fix["placement"], fix.get("turn") or block.turn
                block.confidence, block.uncertain, block.alternatives = 1.0, [], {}
        result = analyze(book.doc)
        # Scans: a second reading with each figurine read by its shape, kept if it reads better.
        result = figurines.read_by_shape(book, result, d / "glyphs.npz")
        data = result.to_dict()
        for diagram in data["diagrams"]:
            diagram["corrected"] = diagram["key"] in corrections
        layout = book.export(d, result.marks())
        _write_json(d / "layout.json", layout)
        _write_json(d / "analysis.json", data)
        _write_json(d / "pgn.json", {g.id: g.to_pgn() for g in result.anchored.games})
        _update_meta(book_id, status="ready", stats=data["stats"], progress=None)
    except ingest.UnsupportedFormat as e:
        _update_meta(book_id, status="error", error=f"unsupported: {e}")
    except Exception as e:  # report any parser failure on the book instead of losing it
        log.exception("analysis of %s failed", book_id)
        _update_meta(book_id, status="error", error=repr(e))


def _update_meta(book_id: str, **changes) -> None:
    with _lock:
        path = book_dir(book_id) / "meta.json"
        _write_json(path, {**_read_json(path), **changes})


# --- The trainer (one record for the whole library) ---

TRAINER_LIMIT = 10_000_000  # bytes of JSON


def trainer_record() -> dict:
    path = DATA_DIR / "trainer.json"
    return trainer.complete(_read_json(path) if path.is_file() else None)


def save_trainer_record(record: dict) -> None:
    if len(json.dumps(record)) > TRAINER_LIMIT:
        raise ValueError("the trainer record is too large")
    with _lock:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _write_json(DATA_DIR / "trainer.json", record)


def trainer_session(test: bool = False) -> dict:
    return trainer.build_session(books_dir(), list_books(), trainer_record(), test=test)


def trainer_books() -> list[dict]:
    return trainer.books_overview(books_dir(), list_books(), trainer_record())


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
