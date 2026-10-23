"""Book storage: one folder per book, in the library of the reader who imported it.

The local app has one reader, whose library is the data directory itself. A hosted app keeps each
account's library apart, in <data>/users/<account id>/, and a request only ever looks in the
library of the account that made it: another reader's book is simply not found.

    <data>/incoming/                    uploads still arriving
    <library>/trainer.json              the trainer's record
    <library>/books/<sha1>/book.<ext>   the original file
                        meta.json       title, format, analysis status
                        disabled.json   hosted app: why the book was disabled after a copyright
                                        notice (its owner can't open it); see copyright.py
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
import secrets
import shutil
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from . import config, ingest, jobs, trainer
from .parse import analyze
from .vision import figurines

log = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("CBV_DATA_DIR", "~/.local/share/chess-books-visualizer")).expanduser()
_ID = re.compile(r"^[0-9a-f]{40}$")
_ACCOUNT = re.compile(r"^[0-9a-f]{32}$")
# The reader of the local app.
LOCAL = "local"
_lock = threading.Lock()
# An EPUB is a zip file: one that would unpack to more than this is refused (a "zip bomb").
EPUB_MAX_FILES = 10_000
EPUB_MAX_UNPACKED = 2**30


class NotFound(Exception):
    pass


class Disabled(Exception):
    """The book was disabled after a copyright notice: its owner sees it listed, but can't open it."""


class Refused(Exception):
    """An upload that isn't taken: ``why`` says why, with the HTTP status that tells it."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status, self.why = status, why


def user_dir(user: str) -> Path:
    """The library of a reader: the local one, or an account of the hosted app."""
    if user == LOCAL:
        return DATA_DIR
    if not _ACCOUNT.match(user):
        raise NotFound(user)
    return DATA_DIR / "users" / user


def books_dir(user: str) -> Path:
    return user_dir(user) / "books"


def book_dir(user: str, book_id: str) -> Path:
    if not _ID.match(book_id):
        raise NotFound(book_id)
    d = books_dir(user) / book_id
    if not d.is_dir():
        raise NotFound(book_id)
    return d


def readable_dir(user: str, book_id: str) -> Path:
    """A book's folder, to read what is in the book: not while it is disabled."""
    d = book_dir(user, book_id)
    if (d / "disabled.json").is_file():
        raise Disabled(book_id)
    return d


def set_disabled(user: str, book_id: str, why: dict | None) -> None:
    """Disables a book after a copyright notice (``why`` is shown to its owner), or, with None,
    lets its owner open it again. Kept apart from meta.json, which the analysis rewrites as it goes."""
    path = book_dir(user, book_id) / "disabled.json"
    if why is None:
        path.unlink(missing_ok=True)
    else:
        _write_json(path, why)


def list_books(user: str) -> list[dict]:
    if not books_dir(user).is_dir():
        return []
    metas = [_meta(d) for d in books_dir(user).iterdir() if (d / "meta.json").is_file()]
    return sorted(metas, key=lambda m: m["imported_at"], reverse=True)


def get_book(user: str, book_id: str) -> dict:
    return _meta(book_dir(user, book_id))


def _meta(d: Path) -> dict:
    meta = _read_json(d / "meta.json")
    if (d / "disabled.json").is_file():
        meta["disabled"] = _read_json(d / "disabled.json")
    return meta


@dataclass
class Received:
    """An uploaded file, set aside until it is imported (and deleted if it isn't)."""

    path: Path
    format: str  # "pdf" or "epub": what the file holds, whatever its name says
    size: int
    sha1: str  # the book's id
    sha256: str  # its fingerprint, to find the copies a copyright notice names

    def __enter__(self) -> Received:
        return self

    def __exit__(self, *_) -> None:
        self.path.unlink(missing_ok=True)


def receive(stream: BinaryIO) -> Received:
    """Copies an uploaded book to disk, a piece at a time, and checks it is one: a PDF or an EPUB,
    no larger than config.MAX_UPLOAD_MB, that doesn't unpack to too much."""
    incoming = DATA_DIR / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    path = incoming / f"{secrets.token_hex(8)}.part"
    sha1, sha256, size, head = hashlib.sha1(), hashlib.sha256(), 0, b""
    limit = config.MAX_UPLOAD_MB * 2**20
    try:
        with path.open("wb") as out:
            while chunk := stream.read(2**20):
                size += len(chunk)
                if limit and size > limit:
                    raise Refused(413, "too_big")
                head = head or chunk[:1024]
                sha1.update(chunk)
                sha256.update(chunk)
                out.write(chunk)
        if b"%PDF-" in head:
            fmt = "pdf"
        elif head.startswith(b"PK\x03\x04"):
            fmt = "epub"
            _check_epub(path)
        else:
            raise Refused(415, "format")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return Received(path, fmt, size, sha1.hexdigest(), sha256.hexdigest())


def _check_epub(path: Path) -> None:
    """An EPUB is a zip file with a container.xml, whose files say how large they unpack to (and
    zipfile never unpacks more than that)."""
    try:
        with zipfile.ZipFile(path) as z:
            entries = z.infolist()
    except zipfile.BadZipFile:
        raise Refused(415, "format") from None
    if "META-INF/container.xml" not in {e.filename for e in entries}:
        raise Refused(415, "format")
    if len(entries) > EPUB_MAX_FILES or sum(e.file_size for e in entries) > EPUB_MAX_UNPACKED:
        raise Refused(413, "unpacked")


def import_book(user: str, filename: str, upload: Received, declared: bool = False,
                limits: tuple[int, int] | None = None) -> dict:
    """A new book in the reader's library, from what ``receive`` took. ``declared``: the reader
    said it is theirs to use (the hosted app asks), and when is kept with it. ``limits``: the most
    books and megabytes the library may keep (by default the free plan's)."""
    book_id = upload.sha1
    d = books_dir(user) / book_id
    max_books, max_mb = limits or (config.MAX_BOOKS, config.MAX_STORAGE_MB)
    with _lock:
        if (d / "meta.json").is_file():
            return get_book(user, book_id)
        books, used = usage(user)
        if max_books and books >= max_books:
            raise Refused(403, "books")
        if max_mb and used + upload.size > max_mb * 2**20:
            raise Refused(403, "storage")
        d.mkdir(parents=True, exist_ok=True)
        upload.path.replace(d / f"book.{upload.format}")
        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "id": book_id,
            "title": Path(filename).stem,
            "filename": filename,
            "format": upload.format,
            "status": "queued",
            "error": None,
            "stats": None,
            "imported_at": now,
            "sha256": upload.sha256,
        }
        if declared:
            meta["declared_at"] = now
        _write_json(d / "meta.json", meta)
    start_analysis(user, book_id)
    return meta


def usage(user: str) -> tuple[int, int]:
    """How many books a library has, and the bytes of their files (not what was read from them)."""
    files = list(books_dir(user).glob("*/book.*")) if books_dir(user).is_dir() else []
    return len(files), sum(f.stat().st_size for f in files)


def resume_unfinished() -> None:
    """Restarts analyses that were cut short (the server stopped while they ran), and forgets
    uploads it was receiving."""
    shutil.rmtree(DATA_DIR / "incoming", ignore_errors=True)
    accounts = DATA_DIR / "users"
    if not config.HOSTED:
        readers = [LOCAL]
    else:
        readers = [d.name for d in accounts.iterdir() if _ACCOUNT.match(d.name)] if accounts.is_dir() else []
    for user in readers:
        for meta in list_books(user):
            if meta["status"] in ("queued", "analyzing") and "disabled" not in meta:
                start_analysis(user, meta["id"])


def delete_book(user: str, book_id: str) -> None:
    shutil.rmtree(book_dir(user, book_id))


def delete_user(user: str) -> None:
    """Everything an account kept: its books, what was read from them, its training record."""
    if user == LOCAL:
        raise ValueError("the local library is not an account")
    shutil.rmtree(user_dir(user), ignore_errors=True)


def start_analysis(user: str, book_id: str) -> None:
    readable_dir(user, book_id)
    _update_meta(user, book_id, status="queued", error=None, progress=None)
    jobs.submit(user, (user, book_id), lambda: _analyze(user, book_id))


def analysis(user: str, book_id: str) -> dict:
    path = readable_dir(user, book_id) / "analysis.json"
    if not path.is_file():
        raise NotFound(book_id)
    return _read_json(path)


def layout(user: str, book_id: str) -> dict:
    path = readable_dir(user, book_id) / "layout.json"
    if not path.is_file():
        raise NotFound(book_id)
    return _read_json(path)


def page_marks(user: str, book_id: str, page: int) -> list:
    path = readable_dir(user, book_id) / "pages" / f"{page}.json"
    return _read_json(path) if path.is_file() else []


def page_image(user: str, book_id: str, page: int, zoom: float) -> Path:
    """PNG of a PDF page, rendered once and cached."""
    from .ingest.pdf import render_page

    d = readable_dir(user, book_id)
    pages = len(layout(user, book_id).get("pages", []))
    if not 0 <= page < pages:
        raise NotFound(str(page))
    cached = d / "render" / f"{page}@{zoom:g}.png"
    if cached.is_file():
        os.utime(cached)  # seen now: see forget_renders
    else:
        cached.parent.mkdir(exist_ok=True)
        tmp = cached.with_suffix(f".{secrets.token_hex(4)}.tmp")
        tmp.write_bytes(render_page(d / "book.pdf", page, zoom))
        tmp.replace(cached)
    return cached


# A hosted site keeps a page image this many days after it was last looked at (see forget_renders).
RENDER_DAYS = 7


def forget_renders(days: int = RENDER_DAYS) -> int:
    """Deletes the page images of the hosted site's libraries that nobody looked at in ``days``
    (they are rendered again when needed); returns how many."""
    old = time.time() - days * 86400
    forgotten = 0
    for png in DATA_DIR.glob("users/*/books/*/render/*.png"):
        if png.stat().st_mtime < old:
            png.unlink(missing_ok=True)
            forgotten += 1
    return forgotten


def epub_file(user: str, book_id: str, path: str) -> tuple[bytes, str]:
    """A chapter (annotated) or resource of an EPUB book."""
    d = readable_dir(user, book_id)
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


def correct_diagram(user: str, book_id: str, key: str, fen_placement: str, turn: str | None) -> dict:
    """Saves the reader's fix of a diagram's position and re-analyses the book with it."""
    import chess

    d = readable_dir(user, book_id)
    chess.Board(f"{fen_placement} w - - 0 1")  # raises ValueError if the placement is malformed
    with _lock:
        corrections = _corrections(d)
        corrections[key] = {"placement": fen_placement, "turn": turn}
        _write_json(d / "corrections.json", corrections)
    start_analysis(user, book_id)
    return get_book(user, book_id)


def _corrections(d: Path) -> dict:
    path = d / "corrections.json"
    return _read_json(path) if path.is_file() else {}


# What the reader saves for a book: kept apart from the analysis, which may be rebuilt at any time.
USER_DATA = {"progress", "annotations"}
USER_DATA_LIMIT = 5_000_000  # bytes of JSON per file


def user_data(user: str, book_id: str, name: str) -> dict:
    path = book_dir(user, book_id) / f"{name}.json"
    return _read_json(path) if path.is_file() else {}


def save_user_data(user: str, book_id: str, name: str, data: dict) -> None:
    if name not in USER_DATA:
        raise NotFound(name)
    if len(json.dumps(data)) > USER_DATA_LIMIT:
        raise ValueError(f"{name} is too large")
    with _lock:
        _write_json(book_dir(user, book_id) / f"{name}.json", data)


def move_fixes(user: str, book_id: str) -> list[dict]:
    path = readable_dir(user, book_id) / "move_fixes.json"
    return _read_json(path) if path.is_file() else []


def save_move_fixes(user: str, book_id: str, fixes: list[dict]) -> dict:
    """Saves the reader's move fixes (all of them) and analyses the book again with them."""
    import chess

    for fix in fixes:
        if not isinstance(fix.get("page"), int) or len(fix.get("rect") or []) != 4:
            raise ValueError("a fix needs a page and a rect")
        if not fix.get("remove"):
            board = chess.Board(fix.get("before") or "")  # raises ValueError if the FEN is malformed
            if chess.Move.from_uci(fix.get("uci") or "0000") not in board.legal_moves:
                raise ValueError(f"{fix.get('uci')} is not legal in {fix.get('before')}")
    d = readable_dir(user, book_id)
    with _lock:
        _write_json(d / "move_fixes.json", fixes)
    start_analysis(user, book_id)
    return get_book(user, book_id)


def game_pgn(user: str, book_id: str, game_id: str) -> str:
    pgns = _read_json(readable_dir(user, book_id) / "pgn.json")
    if game_id not in pgns:
        raise NotFound(game_id)
    return pgns[game_id]


def _analyze(user: str, book_id: str) -> None:
    """Analyses a book in a worker process (see jobs.py), and tells how it went in its meta."""
    try:
        d = book_dir(user, book_id)
    except NotFound:  # deleted while it waited
        return
    _set_meta(d, status="analyzing")
    try:
        stats = jobs.run(_read_book, d, progress=lambda f: _set_meta(d, progress=round(f, 2)),
                         minutes=config.ANALYSIS_MINUTES, memory_mb=config.ANALYSIS_MEMORY_MB)
        _set_meta(d, status="ready", stats=stats, progress=None)
    except ingest.UnsupportedFormat as e:
        _set_meta(d, status="error", error=f"unsupported: {e}")
    except jobs.Limit as e:
        _set_meta(d, status="error", error=f"limit: {e.what}", progress=None)
    except Exception as e:  # report any parser failure on the book instead of losing it
        if (d / "meta.json").is_file():
            log.error("analysis of %s failed: %r", book_id, e)
            _set_meta(d, status="error", error=repr(e), progress=None)
    finally:
        # Deleted while it was read (the book, or the whole account): what the analysis wrote
        # since must not stay behind.
        if not (d / "meta.json").is_file():
            shutil.rmtree(d, ignore_errors=True)


def _read_book(d: Path, progress) -> dict:
    """In a worker process: reads the book in folder ``d`` and writes what was found in it next to
    it. Returns its stats."""
    source = next(d.glob("book.*"))
    book = ingest.open_book(source, cache=d / "vision.json", progress=progress)
    fixes_path = d / "move_fixes.json"
    fixes = _read_json(fixes_path) if fixes_path.is_file() else []
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
    return data["stats"]


def _update_meta(user: str, book_id: str, **changes) -> None:
    _set_meta(book_dir(user, book_id), **changes)


def _set_meta(d: Path, **changes) -> None:
    with _lock:
        path = d / "meta.json"
        _write_json(path, {**_read_json(path), **changes})


# --- The trainer (one record for each reader's whole library) ---

TRAINER_LIMIT = 10_000_000  # bytes of JSON


def trainer_record(user: str) -> dict:
    path = user_dir(user) / "trainer.json"
    return trainer.complete(_read_json(path) if path.is_file() else None)


def save_trainer_record(user: str, record: dict) -> None:
    if len(json.dumps(record)) > TRAINER_LIMIT:
        raise ValueError("the trainer record is too large")
    with _lock:
        user_dir(user).mkdir(parents=True, exist_ok=True)
        _write_json(user_dir(user) / "trainer.json", record)


def trainer_session(user: str, test: bool = False) -> dict:
    return trainer.build_session(books_dir(user), _trainable(user), trainer_record(user), test=test)


def trainer_books(user: str) -> list[dict]:
    return trainer.books_overview(books_dir(user), _trainable(user), trainer_record(user))


def _trainable(user: str) -> list[dict]:
    return [meta for meta in list_books(user) if "disabled" not in meta]


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(f".{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
