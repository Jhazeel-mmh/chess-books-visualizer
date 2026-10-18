"""How well a book's diagrams were read: python scripts/diagram_audit.py <book> [--cache file] [--sheet out.png].

Reports gaps in the diagram numbering (boards or numbers missed), how sure the readings are,
and the diagrams the reader lists for checking, with the reason. ``--sheet`` draws those
diagrams as printed next to the position read, to look over by eye.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend" / "tools"))

from cbv import ingest  # noqa: E402
from cbv.parse import analyze  # noqa: E402


def main(path: Path, cache: Path | None, sheet: Path | None, count: int) -> None:
    book = ingest.open_book(path, cache=cache)
    result = analyze(book.doc)
    diagrams = result.diagrams()
    print(path.name)

    numbers = sorted({int(d["label"]) for d in diagrams if d["label"] and d["label"].isdigit()})
    missing = [n for n in range(1, numbers[-1] + 1) if n not in set(numbers)] if numbers else []
    print(f"  diagrams: {len(diagrams)}  numbered: {sum(1 for d in diagrams if d['label'])}"
          f"  numbers missing up to {numbers[-1] if numbers else '-'}: {len(missing)} {missing[:20]}")

    image = [d for d in diagrams if d["confidence"] is not None and d["confidence"] < 1]
    bands = Counter("<0.6" if d["confidence"] < 0.6 else "<0.9" if d["confidence"] < 0.9 else ">=0.9" for d in image)
    print(f"  read from images: {len(image)}  certainty {dict(bands)}")
    print(f"  linked to moves: {sum(1 for d in diagrams if d['node'])}  corrected from their solution: "
          f"{sum(1 for d in diagrams if d['fixed'])}")

    reasons = Counter(r for d in diagrams for r in d["check"])
    to_check = [d for d in diagrams if d["to_check"]]
    print(f"  to check: {len(to_check)}  notes on all diagrams: {dict(reasons)}")
    for d in to_check[:15]:
        print(f"    {d['label'] or '-':>6} block {d['block']:5} {d['placement']} {', '.join(d['check'])}")

    if sheet and to_check:
        _sheet(path, book, to_check[:count], sheet)
        print(f"  sheet of {min(count, len(to_check))} diagrams saved to {sheet}")


def _sheet(path: Path, book, diagrams: list[dict], out: Path) -> None:
    import cv2
    import numpy as np
    import pymupdf
    from vision_sheet import draw

    size, tiles = 300, []
    pdf = pymupdf.open(path) if path.suffix.lower() == ".pdf" else None
    for d in diagrams:
        block = book.doc.blocks[d["block"]]
        if pdf is None or not d["placement"]:
            continue
        x0, y0, x1, y1 = block.source.bbox
        pix = pdf[block.source.page].get_pixmap(dpi=200, clip=pymupdf.Rect(x0 - 3, y0 - 3, x1 + 3, y1 + 3),
                                                colorspace=pymupdf.csGRAY)
        printed = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        printed = cv2.resize(printed, (size, size), interpolation=cv2.INTER_AREA)
        pair = np.hstack([printed, np.full((size, 8), 255, np.uint8), draw(d["placement"], d["uncertain"], size)])
        pair = cv2.copyMakeBorder(pair, 22, 8, 8, 8, cv2.BORDER_CONSTANT, value=255)
        caption = f"#{d['label'] or '-'} p{block.source.page + 1} {d['confidence'] or 1:.2f} {','.join(d['check'])}"
        cv2.putText(pair, caption, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)
        tiles.append(pair)
    if not tiles:
        return
    while len(tiles) % 2:
        tiles.append(np.full_like(tiles[0], 255))
    cv2.imwrite(str(out), np.vstack([np.hstack(tiles[r:r + 2]) for r in range(0, len(tiles), 2)]))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("book", type=Path)
    ap.add_argument("--cache", type=Path, help="file to keep diagrams read from images between runs")
    ap.add_argument("--sheet", type=Path, help="image file for the diagrams to check")
    ap.add_argument("--count", type=int, default=12, help="diagrams on the sheet")
    args = ap.parse_args()
    main(args.book, args.cache, args.sheet, args.count)
