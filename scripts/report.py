"""Prints how well the parser reads a book: python scripts/report.py <book file> [--cache file]."""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import chess  # noqa: E402

from cbv import ingest  # noqa: E402
from cbv.parse import analyze  # noqa: E402


def _valid(placement: str) -> bool:
    return any(chess.Board(f"{placement} {side} - - 0 1").is_valid() for side in "wb")


def main(path: Path, cache: Path | None = None) -> None:
    t0 = time.perf_counter()
    doc = ingest.open_book(path, cache=cache).doc
    t1 = time.perf_counter()
    result = analyze(doc)
    t2 = time.perf_counter()
    a = result.anchored

    pct = 100 * a.moves_resolved / a.moves_found if a.moves_found else 0
    print(f"{path.name}")
    print(f"  blocks: {len(doc.blocks)}  (read in {t1 - t0:.1f}s, parsed in {t2 - t1:.1f}s)")
    print(f"  notation: {result.pieces.describe()}  main-line style: {result.style}")
    print(f"  games: {len(a.games)}  nodes: {sum(len(g.nodes()) - 1 for g in a.games)}")
    print(f"  moves linked: {a.moves_resolved}/{a.moves_found} ({pct:.1f}%)")
    print(f"  unresolved fragments: {len(a.unresolved)}  {dict(Counter(u.reason for u in a.unresolved))}")
    diagrams = result.diagrams()
    read = [d for d in diagrams if d["placement"]]
    valid = [d for d in read if _valid(d["placement"])]
    unsure = [d for d in read if (d["confidence"] or 1) < 0.6]
    print(f"  diagrams: {len(diagrams)}  read: {len(read)}  legal positions: {len(valid)}  "
          f"linked to moves: {sum(1 for d in diagrams if d['node'])}  low confidence: {len(unsure)}")
    for u in a.unresolved[:25]:
        print(f"    [{u.reason:11}] block {u.refs[0].block}: {u.text}")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("book", type=Path)
    ap.add_argument("--cache", type=Path, help="file to keep diagrams read from images between runs")
    args = ap.parse_args()
    main(args.book, args.cache)
