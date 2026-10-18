"""The daily trainer: sessions that mix calculation, endgame play-out, reading and guess-the-move,
drawn from every book in the library.

It follows GM Noël Studer's advice: solve unseen positions to the end, without hints, the way you
would in a game; take tests of several mixed positions and revisit the missed ones later; work on
one thing at a time. The record of what was trained (``trainer.json`` in the data folder) is kept
by the app; this module builds a session from it and from the books' analyses.
"""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chess

ROLES = ("tactics", "endgames", "concepts", "games", "skip")

# Share of a session for each block, and how one focus changes it.
SHARES = {"calculation": 0.4, "endgame": 0.22, "reading": 0.2, "guess": 0.18}
FOCUS_BLOCKS = {"calculation": ("calculation",), "endgames": ("endgame",), "positional": ("reading", "guess")}
FOCUS_BOOST = 1.6
MINUTES_PER_POSITION = 6
# Studer's test: six positions in 45 minutes, solutions after all of them.
TEST_POSITIONS = 6
TEST_MINUTES = 45
GUESS_MOVES = 10
# A game is worth guessing from this many plies; a fresh one starts after the opening.
GUESS_MIN_PLIES = 40
GUESS_START_PLY = 12
# How deep a problem's solution is sent (plies from the diagram).
SOLUTION_PLIES = 30
# Missed positions come back after a week, then after a month.
RETRY_DAYS = (7, 30)
# Pieces on the board (kings included) for an endgame from an endgame book, and from any other.
ENDGAME_PIECES = 12
FEW_PIECES = 7

DEFAULT_RECORD = {
    "settings": {"minutes": 50, "rating": 1800, "focus": None},
    "level": None,
    "roles": {},
    "positions": {},
    "reading": {"book": None, "at": {}},
    "games": {"current": None, "at": {}},
    # The books the reader picked for each subject (calculation, endgame, reading, guess); a subject
    # not listed takes its books by their roles.
    "sources": {},
    "sessions": [],
    "current": None,
}


def complete(record: dict | None) -> dict:
    """A record with every field present (older or empty ones get the defaults)."""
    out = json.loads(json.dumps(DEFAULT_RECORD))
    for key, value in (record or {}).items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def level_for(rating: int) -> float:
    """The starting difficulty (1–6) for a rating: 1600 → 2.5, 1800 → 3, 2000 → 3.5."""
    return min(6.0, max(1.0, 2.5 + (rating - 1600) / 400))


# --- What the books hold ------------------------------------------------------------------------


@dataclass
class Problem:
    book: str
    key: str
    diagram: str
    root: str
    fen: str
    plies: int
    difficulty: float
    label: str | None = None


@dataclass
class BookPool:
    id: str
    title: str
    guessed_role: str
    kind: str  # pdf or epub
    length: int  # pages or chapters
    problems: list[Problem] = field(default_factory=list)
    endgames: list[dict] = field(default_factory=list)
    games: list[dict] = field(default_factory=list)  # {id, title, plies, root}
    nodes: dict = field(default_factory=dict, repr=False)  # the book's moves by id


_ENDGAME_TITLE = re.compile(r"final|endgame|endspiel|finale", re.I)
_LEVEL_SECTION = {"easy": -0.5, "fácil": -0.5, "facil": -0.5, "advanced": 1.0, "avanzad": 1.0}


def guess_role(title: str, problems: int, diagrams: int) -> str:
    if _ENDGAME_TITLE.search(title or ""):
        return "endgames"
    if problems >= 300 or (diagrams and problems / diagrams >= 0.6):
        return "tactics"
    return "concepts"


def difficulty(plies: int, points: int | None, section: str | None) -> float:
    """1 (a one-mover) to 6: the solver's moves in the book's line, the book's own points, its level."""
    d = float(min(5, math.ceil(plies / 2)))
    if points:
        d = (d + points) / 2
    title = (section or "").lower()
    d += next((v for k, v in _LEVEL_SECTION.items() if k in title), 0.0)
    return max(1.0, min(6.0, d))


def _pieces(fen: str) -> int:
    return sum(c.isalpha() for c in fen.split()[0])


def _playable(fen: str) -> bool:
    try:
        board = chess.Board(fen)
    except ValueError:
        return False
    return board.is_valid() and not board.is_game_over()


def _diagram_fen(d: dict, nodes: dict) -> str | None:
    if d.get("node") in nodes:
        return nodes[d["node"]]["fen"]
    if d.get("placement") and d.get("turn"):
        return f"{d['placement']} {d['turn']} - - 0 1"
    return None


def _mainline_plies(nodes: dict, start: str) -> int:
    n, plies = nodes[start], 0
    while n["children"] and plies < 400:
        n = nodes[n["children"][0]]
        plies += 1
    return plies


def book_pool(book_dir: Path, meta: dict) -> BookPool:
    analysis = json.loads((book_dir / "analysis.json").read_text())
    layout = json.loads((book_dir / "layout.json").read_text())
    nodes = {n["id"]: n for g in analysis["games"] for n in g["nodes"]}
    diagrams = analysis["diagrams"]
    problems_count = sum(1 for d in diagrams if d.get("problem"))
    kind = layout["kind"]
    pool = BookPool(
        id=meta["id"],
        title=meta.get("title") or meta["id"],
        guessed_role=guess_role(meta.get("title", ""), problems_count, len(diagrams)),
        kind=kind,
        length=len(layout["pages"] if kind == "pdf" else layout["chapters"]),
        nodes=nodes,
    )
    for d in diagrams:
        fen = _diagram_fen(d, nodes)
        if not fen or not d.get("key") or d.get("to_check"):
            continue
        if d.get("problem") and d.get("node") in nodes:
            plies = _mainline_plies(nodes, d["node"])
            if plies:
                pool.problems.append(Problem(
                    book=pool.id, key=d["key"], diagram=d["id"], root=d["node"], fen=fen, plies=plies,
                    difficulty=difficulty(plies, d.get("points"), d.get("section")), label=d.get("label"),
                ))
        if _pieces(fen) <= ENDGAME_PIECES and _playable(fen):
            pool.endgames.append({"book": pool.id, "key": d["key"], "fen": fen, "pieces": _pieces(fen)})
    for g in analysis["games"]:
        plies = _mainline_plies(nodes, g["root"])
        if plies >= GUESS_MIN_PLIES:
            pool.games.append({"id": g["id"], "title": g.get("title"), "plies": plies, "root": g["root"]})
    return pool


_cache: dict[str, tuple[float, BookPool]] = {}


def pools(books_dir: Path, metas: list[dict]) -> list[BookPool]:
    """Every ready book's pool, cached until the book is analysed again."""
    out = []
    for meta in metas:
        d = books_dir / meta["id"]
        path = d / "analysis.json"
        if meta.get("status") != "ready" or not path.is_file():
            continue
        mtime = path.stat().st_mtime
        hit = _cache.get(meta["id"])
        if not hit or hit[0] != mtime:
            hit = (mtime, book_pool(d, meta))
            _cache[meta["id"]] = hit
        out.append(hit[1])
    return out


def role_of(pool: BookPool, record: dict) -> str:
    return record["roles"].get(pool.id) or pool.guessed_role


SUBJECTS = ("calculation", "endgame", "reading", "guess")
# A book's problems count for calculation if it is a tactics book, or has at least this many.
MIN_PROBLEMS = 40


def _endgame_limit(pool: BookPool, record: dict) -> int:
    return ENDGAME_PIECES if role_of(pool, record) == "endgames" else FEW_PIECES


def material(pool: BookPool, record: dict) -> dict[str, int]:
    """What each subject can take from a book: problems, endgame positions, pages or chapters, games."""
    limit = _endgame_limit(pool, record)
    return {
        "calculation": len(pool.problems),
        "endgame": sum(1 for e in pool.endgames if e["pieces"] <= limit),
        "reading": pool.length,
        "guess": len(pool.games),
    }


def default_books(pools_: list[BookPool], record: dict, subject: str) -> list[BookPool]:
    """The books a subject uses until the reader picks some: by each book's role."""
    usable = [p for p in pools_ if role_of(p, record) != "skip"]
    if subject == "calculation":
        return [p for p in usable if p.problems and (role_of(p, record) == "tactics" or len(p.problems) >= MIN_PROBLEMS)]
    if subject == "endgame":
        books = [p for p in usable if role_of(p, record) == "endgames" and p.endgames]
        return books or [p for p in usable if material(p, record)["endgame"]]
    if subject == "reading":
        readable = sorted((p for p in usable if role_of(p, record) in ("concepts", "endgames")), key=lambda p: p.title.lower())
        current = next((p for p in readable if p.id == record["reading"].get("book")), None)
        return [current] if current else readable[:1]
    return [p for p in usable if p.games]


def books_for(pools_: list[BookPool], record: dict, subject: str) -> list[BookPool]:
    """The books a subject draws from: the reader's pick (those with something for it), or the default."""
    chosen = record["sources"].get(subject)
    if chosen is None:
        return default_books(pools_, record, subject)
    return [p for p in pools_ if p.id in chosen and material(p, record)[subject]]


# --- A session ----------------------------------------------------------------------------------


def split(minutes: int, focus: str | None) -> list[tuple[str, int]]:
    """The session's blocks and their minutes, in the order they are done."""
    shares = dict(SHARES)
    for block in FOCUS_BLOCKS.get(focus or "", ()):
        shares[block] *= FOCUS_BOOST
    total = sum(shares.values())
    out, used = [], 0
    for block in SHARES:
        m = round(minutes * shares[block] / total)
        out.append([block, m])
        used += m
    out[0][1] += minutes - used  # rounding goes to calculation
    return [(b, m) for b, m in out]


def _parse(iso: str) -> datetime:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def due(history: list[dict], now: datetime) -> bool:
    """A missed position comes back after a week; once solved, once more after a month; then it is done."""
    if not history:
        return False
    last = history[-1]
    missed = [h for h in history if h.get("result") not in ("full", "met")]
    if not missed:
        return False
    if last.get("result") not in ("full", "met"):
        wait = RETRY_DAYS[0]
    elif len(history) - history.index(missed[-1]) - 1 == 1:
        wait = RETRY_DAYS[1]  # solved once since the last miss: one more look later
    else:
        return False
    return _parse(last["at"]) + timedelta(days=wait) <= now


def _subtree(nodes: dict, root: str) -> list[dict]:
    out, todo = [], [(root, 0)]
    while todo:
        nid, depth = todo.pop()
        n = nodes[nid]
        keep = depth < SOLUTION_PLIES
        out.append({k: n[k] for k in ("id", "parent", "san", "uci", "fen", "nags", "mainline")} | {"children": n["children"] if keep else []})
        if keep:
            todo.extend((c, depth + 1) for c in n["children"] if c in nodes)
    return out


def _pick_problems(books: list[BookPool], record: dict, level: float, count: int, now: datetime, rng: random.Random) -> list[Problem]:
    positions = record["positions"]
    candidates = [p for pool in books for p in pool.problems]
    retry = [p for p in candidates if due(positions.get(f"{p.book}:{p.key}", []), now)]
    rng.shuffle(retry)
    chosen = retry[: max(1, count // 2) if retry else 0]
    taken = {(p.book, p.key) for p in chosen}
    unseen_by_book: dict[str, list[Problem]] = {}
    for p in candidates:
        if f"{p.book}:{p.key}" not in positions and (p.book, p.key) not in taken:
            unseen_by_book.setdefault(p.book, []).append(p)
    books = list(unseen_by_book)
    rng.shuffle(books)
    # One book after another, so that a test mixes books (and nobody knows the chapter's theme).
    while len(chosen) < count and books:
        for book in list(books):
            if len(chosen) >= count:
                break
            pool = unseen_by_book[book]
            for width in (0.75, 1.5, 6):
                near = [p for p in pool if abs(p.difficulty - level) <= width]
                if near:
                    p = rng.choice(near)
                    pool.remove(p)
                    chosen.append(p)
                    break
            if not pool:
                books.remove(book)
    rng.shuffle(chosen)
    return chosen


def build_session(books_dir: Path, metas: list[dict], record: dict, test: bool = False,
                  now: datetime | None = None, seed: int | None = None) -> dict:
    record = complete(record)
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    pools_ = pools(books_dir, metas)
    by_id = {p.id: p for p in pools_}
    settings = record["settings"]
    level = record["level"] or level_for(int(settings.get("rating") or 1800))
    plan = [("calculation", TEST_MINUTES)] if test else split(int(settings.get("minutes") or 50), settings.get("focus"))
    blocks = []
    for kind, minutes in plan:
        items: list[dict] = []
        if kind == "calculation":
            count = TEST_POSITIONS if test else max(2, round(minutes / MINUTES_PER_POSITION))
            for p in _pick_problems(books_for(pools_, record, kind), record, level, count, now, rng):
                items.append({
                    "book": p.book, "key": p.key, "diagram": p.diagram, "label": p.label, "fen": p.fen,
                    "root": p.root, "tree": _subtree(by_id[p.book].nodes, p.root), "difficulty": p.difficulty,
                    "bookTitle": by_id[p.book].title,
                })
        elif kind == "endgame":
            item = _pick_endgame(books_for(pools_, record, kind), record, rng)
            if item:
                items.append(item | {"bookTitle": by_id[item["book"]].title})
        elif kind == "reading":
            item = _pick_reading(books_for(pools_, record, kind), record)
            if item:
                items.append(item)
        elif kind == "guess":
            item = _pick_game(books_for(pools_, record, kind), record, rng)
            if item:
                items.append(item)
        if items:
            blocks.append({"kind": kind, "minutes": minutes, "items": items})
    return {
        "id": now.strftime("%Y%m%d%H%M%S"),
        "test": test,
        "level": level,
        "planned": sum(b["minutes"] for b in blocks),
        "blocks": blocks,
    }


def _pick_endgame(books: list[BookPool], record: dict, rng: random.Random) -> dict | None:
    """An unseen endgame position: a book first (each picked book as likely), then a position in it."""
    positions = record["positions"]
    options = {}
    for p in books:
        limit = _endgame_limit(p, record)
        fresh = [e for e in p.endgames if e["pieces"] <= limit and f"{e['book']}:{e['key']}" not in positions]
        if fresh:
            options[p.id] = fresh
    if not options:
        return None
    return dict(rng.choice(options[rng.choice(sorted(options))]))


def _last_read(record: dict) -> dict[str, str]:
    """When each book was last read in a session."""
    out = {}
    for session in record["sessions"]:
        for block in session.get("results", []):
            for r in block:
                if r.get("kind") == "reading":
                    out[r["book"]] = session.get("finished", "")
    return out


def _pick_reading(books: list[BookPool], record: dict) -> dict | None:
    """The book to read on in: the one read longest ago, so that several picked books take turns."""
    if not books:
        return None
    last = _last_read(record)
    pool = min(books, key=lambda p: (last.get(p.id, ""), p.title.lower()))
    at = record["reading"]["at"].get(pool.id)
    return {"book": pool.id, "bookTitle": pool.title, "kind": pool.kind, "at": at, "length": pool.length}


def _pick_game(books: list[BookPool], record: dict, rng: random.Random) -> dict | None:
    games = record["games"]
    candidates = [(p, g) for p in books for g in p.games]
    if not candidates:
        return None
    current = games.get("current")
    pick = next(((p, g) for p, g in candidates if f"{p.id}:{g['id']}" == current), None)
    if pick and (games["at"].get(current) or 0) >= pick[1]["plies"] - 2:
        pick = None  # finished: on to another
    if pick is None:
        unplayed = [(p, g) for p, g in candidates if f"{p.id}:{g['id']}" not in games["at"]]
        titled = [c for c in unplayed if c[1]["title"]]
        pool = titled or unplayed or candidates
        pick = rng.choice(pool)
    pool, game = pick
    nodes = pool.nodes
    line, n = [], nodes[game["root"]]
    while True:
        line.append({k: n[k] for k in ("id", "parent", "san", "uci", "fen", "nags", "mainline")} | {"children": n["children"][:1]})
        if not n["children"]:
            break
        n = nodes[n["children"][0]]
    ref = f"{pool.id}:{game['id']}"
    start = games["at"].get(ref)
    return {
        "book": pool.id, "bookTitle": pool.title, "game": game["id"], "title": game["title"], "line": line,
        "from": start if start is not None else min(GUESS_START_PLY, len(line) - 2), "moves": GUESS_MOVES,
    }


def books_overview(books_dir: Path, metas: list[dict], record: dict) -> list[dict]:
    """What each book holds for each subject, and whether the next session draws from it."""
    record = complete(record)
    pools_ = pools(books_dir, metas)
    used = {subject: {p.id for p in books_for(pools_, record, subject)} for subject in SUBJECTS}
    return [
        {
            "id": p.id, "title": p.title, "kind": p.kind, "role": role_of(p, record),
            "material": material(p, record), "uses": {subject: p.id in used[subject] for subject in SUBJECTS},
        }
        for p in pools_
    ]
