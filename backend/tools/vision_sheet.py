"""Contact sheet of diagrams as read from a book: the printed board beside the position read.

    python tools/vision_sheet.py ../samples/book.pdf sheet.png [--count 24]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cbv.ingest import open_book  # noqa: E402

GLYPHS = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟"))


def draw(placement: str, uncertain: list[int], size: int) -> np.ndarray:
    doc = pymupdf.open()
    page = doc.new_page(width=size, height=size)
    page.insert_font(fontname="dv", fontfile="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    cell = size / 8
    squares = []
    for row in placement.split("/"):
        for ch in row:
            squares.extend([""] * int(ch) if ch.isdigit() else [ch])
    for i, piece in enumerate(squares):
        r, c = divmod(i, 8)
        rect = pymupdf.Rect(c * cell, r * cell, (c + 1) * cell, (r + 1) * cell)
        page.draw_rect(rect, color=None, fill=(0.75, 0.75, 0.75) if (r + c) % 2 else (1, 1, 1))
        if i in uncertain:
            page.draw_rect(rect, color=(0.9, 0.5, 0.1), width=2)
        if piece:
            page.insert_text((rect.x0 + cell * 0.1, rect.y1 - cell * 0.18), GLYPHS[piece], fontname="dv", fontsize=cell * 0.8)
    pix = page.get_pixmap(colorspace=pymupdf.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("book", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--count", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cache", type=Path, help="file to keep diagrams read from images between runs")
    args = ap.parse_args()
    book = open_book(args.book, cache=args.cache)
    diagrams = [b for b in book.doc.blocks if b.kind == "diagram" and b.placement and b.confidence is not None and b.confidence < 1]
    rng = np.random.default_rng(args.seed)
    picks = sorted(rng.choice(len(diagrams), min(args.count, len(diagrams)), replace=False))
    tiles = []
    size = 240
    pdf = pymupdf.open(args.book) if args.book.suffix.lower() == ".pdf" else None
    for i in picks:
        b = diagrams[i]
        if pdf is not None:
            x0, y0, x1, y1 = b.source.bbox
            pix = pdf[b.source.page].get_pixmap(dpi=150, clip=pymupdf.Rect(x0 - 4, y0 - 4, x1 + 4, y1 + 4), colorspace=pymupdf.csGRAY)
            orig = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        else:
            import zipfile
            key = b.key.split("#", 1)[1]
            with zipfile.ZipFile(args.book) as z:
                orig = cv2.imdecode(np.frombuffer(z.read(key), np.uint8), cv2.IMREAD_GRAYSCALE)
        orig = cv2.resize(orig, (size, size), interpolation=cv2.INTER_AREA)
        pair = np.hstack([orig, np.full((size, 6), 255, np.uint8), draw(b.placement, b.uncertain, size)])
        pair = cv2.copyMakeBorder(pair, 18, 6, 6, 6, cv2.BORDER_CONSTANT, value=255)
        cv2.putText(pair, f"{b.label or ''} conf {b.confidence:.2f} turn {b.turn or '?'}", (8, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1)
        tiles.append(pair)
    cols = 3
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 255))
    sheet = np.vstack([np.hstack(tiles[r:r + cols]) for r in range(0, len(tiles), cols)])
    cv2.imwrite(str(args.out), sheet)
    print(f"{len(diagrams)} image diagrams read; sheet with {len(picks)} saved to {args.out}")


if __name__ == "__main__":
    main()
