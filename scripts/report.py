"""Prints how well the parser reads books.

    python scripts/report.py <book file> [--cache file] [--pages]
    python scripts/report.py --library [dir] [--save base.json | --compare base.json]

With ``--library`` every ready book of the app's library is read and parsed again in memory
(nothing in the library is written), one line per book: moves linked, and two precision checks
on the linked moves: of the moves printed with + or #, how many give check on the board; of the
moves printed with x, how many capture. ``--save`` keeps the numbers, ``--compare`` shows the
change against numbers kept before.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import chess  # noqa: E402

from cbv import ingest  # noqa: E402
from cbv.parse import analyze  # noqa: E402
from cbv.vision import figurines  # noqa: E402

LIBRARY = Path(os.environ.get("CBV_DATA_DIR", "~/.local/share/chess-books-visualizer")).expanduser()
# The repository's own scratch folder (not committed): caches the report may write.
SCRATCH = Path(__file__).resolve().parent.parent / ".data"


def _valid(placement: str) -> bool:
    return any(chess.Board(f"{placement} {side} - - 0 1").is_valid() for side in "wb")


def measure(doc, result) -> dict:
    """Moves linked, and how often the linked moves agree with what the book printed (+, #, x)."""
    a = result.anchored
    agree = result.agreement()
    rounded = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in agree.items()}
    return {"found": a.moves_found, "linked": a.moves_resolved, "games": len(a.games), **rounded}


def report_book(path: Path, cache: Path | None = None, pages: bool = False) -> None:
    t0 = time.perf_counter()
    book = ingest.open_book(path, cache=cache, read_only=True)
    doc = book.doc
    t1 = time.perf_counter()
    result = analyze(doc)
    t2 = time.perf_counter()
    a = result.anchored
    m = measure(doc, result)

    pct = 100 * a.moves_resolved / a.moves_found if a.moves_found else 0
    print(f"{path.name}")
    print(f"  blocks: {len(doc.blocks)}  (read in {t1 - t0:.1f}s, parsed in {t2 - t1:.1f}s)")
    print(f"  notation: {result.pieces.describe()}  main-line style: {result.style}")
    print(f"  games: {len(a.games)}  nodes: {sum(len(g.nodes()) - 1 for g in a.games)}")
    print(f"  moves linked: {a.moves_resolved}/{a.moves_found} ({pct:.1f}%)  {_precision(m)}")
    print(f"  unresolved fragments: {len(a.unresolved)}  {dict(Counter(u.reason for u in a.unresolved))}")
    diagrams = result.diagrams()
    read = [d for d in diagrams if d["placement"]]
    valid = [d for d in read if _valid(d["placement"])]
    unsure = [d for d in read if (d["confidence"] or 1) < 0.6]
    print(f"  diagrams: {len(diagrams)}  read: {len(read)}  legal positions: {len(valid)}  "
          f"linked to moves: {sum(1 for d in diagrams if d['node'])}  low confidence: {len(unsure)}")
    if pages:
        _print_pages(doc, a)
    for u in a.unresolved[:25]:
        print(f"    [{u.reason:11}] block {u.refs[0].block}: {u.text}")


def _print_pages(doc, a) -> None:
    """The pages (or chapters) where the most moves stay unlinked."""
    def where(ref):
        return getattr(doc.blocks[ref.block].source, "page", None)
    linked, missed = Counter(), Counter()
    for game in a.games:
        for node in game.nodes():
            for ref in node.refs:
                linked[where(ref)] += 1
    for u in a.unresolved:
        for ref in u.refs:
            missed[where(ref)] += 1
    print("  pages with the most unlinked moves (page: linked / unlinked):")
    for page, n in missed.most_common(12):
        print(f"    {page + 1 if page is not None else '?':>5}: {linked[page]:4} / {n}")


def _precision(m: dict) -> str:
    def pct(v):
        return f"{100 * v:.0f}%" if v is not None else "—"
    return f"checks {pct(m['check_precision'])} of {m['checks']}, captures {pct(m['capture_precision'])} of {m['captures']}"


def library_books(root: Path) -> list[tuple[str, str, Path, Path]]:
    books = []
    for d in sorted((root / "books").iterdir()) if (root / "books").is_dir() else []:
        meta_file = d / "meta.json"
        source = next(d.glob("book.*"), None)
        if not meta_file.is_file() or source is None:
            continue
        meta = json.loads(meta_file.read_text())
        if meta.get("status") == "ready":
            books.append((d.name, meta.get("title") or d.name, source, d / "vision.json"))
    return books


def report_library(root: Path, save: Path | None, compare: Path | None) -> None:
    before = json.loads(compare.read_text()) if compare else {}
    now = {}
    print(f"{'book':40} {'linked':>16}  {'checks':>12}  {'captures':>12}  {'games':>5}")
    for book_id, title, source, cache in library_books(root):
        book = ingest.open_book(source, cache=cache if cache.is_file() else None, read_only=True)
        # Figurine shapes: the library's own cache if it has one (only read), else one kept in .data/.
        glyphs = cache.with_name("glyphs.npz")
        own = not glyphs.is_file()
        if own:
            glyphs = SCRATCH / "glyphs" / f"{book_id}.npz"
            glyphs.parent.mkdir(parents=True, exist_ok=True)
        result = figurines.read_by_shape(book, analyze(book.doc), glyphs, read_only=not own)
        m = measure(book.doc, result)
        now[book_id] = {"title": title, **m}
        print(_row(title, m, before.get(book_id)), flush=True)
    if save:
        save.write_text(json.dumps(now, indent=2, ensure_ascii=False))
        print(f"saved to {save}")


def _row(title: str, m: dict, old: dict | None) -> str:
    def pct(v):
        return f"{100 * v:5.1f}%" if v is not None else "    —"
    share = m["linked"] / m["found"] if m["found"] else 0
    row = f"{title[:40]:40} {m['linked']:6}/{m['found']:6} {pct(share)}  {pct(m['check_precision'])} {m['checks']:5}  " \
          f"{pct(m['capture_precision'])} {m['captures']:5}  {m['games']:5}"
    if old:
        old_share = old["linked"] / old["found"] if old["found"] else 0
        dc = (m["check_precision"] or 0) - (old["check_precision"] or 0)
        row += f"   Δ linked {m['linked'] - old['linked']:+d} ({100 * (share - old_share):+.1f} pts), checks {100 * dc:+.1f} pts"
    return row


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path, nargs="?")
    ap.add_argument("--cache", type=Path, help="file where diagrams read from images are kept (only read)")
    ap.add_argument("--pages", action="store_true", help="show the pages with the most unlinked moves")
    ap.add_argument("--library", type=Path, nargs="?", const=LIBRARY, help="report every book of the library")
    ap.add_argument("--save", type=Path, help="with --library: keep the numbers in this file")
    ap.add_argument("--compare", type=Path, help="with --library: show the change against this file")
    args = ap.parse_args()
    if args.library:
        report_library(args.library, args.save, args.compare)
    elif args.book:
        report_book(args.book, args.cache, args.pages)
    else:
        ap.error("give a book file, or --library")
