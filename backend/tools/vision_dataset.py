"""Builds training squares for the piece classifier (development tool).

    python tools/vision_dataset.py --out data/squares.npz \\
        --woodpecker ../samples/woodpecker.pdf --polgar ../samples/polgar.pdf

Two kinds of boards go through the same code the app uses to cut a board into squares
(``cbv.vision.board.board_from_box``), so training and recognition see identical inputs:

* real typed diagrams from books whose positions are known exactly (Merida and
  LaTeX ``skak`` fonts), rendered at random resolutions;
* synthetic boards: piece glyphs (skak, DejaVu, and Merida pieces cut from the real
  boards) on many square styles (plain, gray, hatched, cross-hatched, dotted). Empty
  squares sometimes carry the marks books print on them (asterisks for key squares,
  digits, letters, dots, crosses, circled square names), which must still read as empty;
  some boards are split by a line, as in diagrams that show two half-boards.

Every board is then damaged like a scan: blur, noise, JPEG, low resolution, faded
ink, thresholding, slight rotation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cbv.vision.board import board_from_box  # noqa: E402

CLASSES = ".PNBRQKpnbrqk"  # index = class id; "." is an empty square
DEJAVU = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
DEJAVU_GLYPHS = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟"))
SKAK_LIGHT = {p: p for p in "KQRBNPkqrbnp"}
SKAK_DARK = dict(zip("KQRBNPkqrbnp", "JLSAMOjlsamo"))
FONTS = "/usr/share/fonts/truetype/dejavu/"
MARK_FONTS = [DEJAVU] + [FONTS + f for f in ("DejaVuSerif.ttf", "DejaVuSans-Bold.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSansCondensed.ttf")]
MARK_TEXTS = list("*x×+•·○●◦?!#=↑→0123456789abcdefgh") + ["✱", "✶", "a8", "f3", "12", "21", "B", "N"]


def placement_labels(placement: str) -> list[int]:
    labels = []
    for row in placement.split("/"):
        for ch in row:
            labels.extend([0] * int(ch) if ch.isdigit() else [CLASSES.index(ch)])
    return labels


# ---------------------------------------------------------------- glyph sprites

def render_glyph(fontfile: str, char: str, px: int = 160) -> np.ndarray:
    """A glyph rendered black on white, cropped to its ink; float32, 1 = paper."""
    doc = pymupdf.open()
    page = doc.new_page(width=px * 2, height=px * 2)
    page.insert_font(fontname="g", fontfile=fontfile)
    page.insert_text((px * 0.3, px * 1.5), char, fontname="g", fontsize=px)
    pix = page.get_pixmap(dpi=72, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(np.float32) / 255
    ys, xs = np.nonzero(img < 0.5)
    if not len(ys):
        raise ValueError(f"glyph {char!r} is empty in {fontfile}")
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def silhouette(sprite: np.ndarray) -> np.ndarray:
    """Pixels inside the piece outline (white pieces have a paper-coloured inside)."""
    ink = (sprite < 0.6).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    padded = np.pad(1 - ink, 1, constant_values=1).astype(np.uint8)
    mask = np.zeros((padded.shape[0] + 2, padded.shape[1] + 2), np.uint8)
    cv2.floodFill(padded, mask, (0, 0), 2)
    outside = padded[1:-1, 1:-1] == 2
    return ~outside


class Sprites:
    """Piece images on a transparent background, per style."""

    def __init__(self):
        self.styles: list[dict[int, list[tuple[np.ndarray, np.ndarray]]]] = []

    def add_font(self, fontfile: str, glyphs: dict[str, str]):
        style = {}
        for piece, char in glyphs.items():
            img = render_glyph(fontfile, char)
            style[CLASSES.index(piece)] = [(img, silhouette(img))]
        self.styles.append(style)

    def add_cells(self, cells: dict[int, list[np.ndarray]]):
        """Pieces cut from light squares of real boards."""
        style = {}
        for label, imgs in cells.items():
            sprites = []
            for img in imgs[:6]:
                ys, xs = np.nonzero(img < 0.5)
                if len(ys) < 10:
                    continue
                crop = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
                sprites.append((crop, silhouette(crop)))
            if sprites:
                style[label] = sprites
        if len(style) == 12:
            self.styles.append(style)


class Marks:
    """Things books print on empty squares: they are not pieces."""

    def __init__(self, rng):
        self.sprites = []
        for text in MARK_TEXTS:
            for font in MARK_FONTS:
                try:
                    img = render_glyph(font, text)
                except ValueError:
                    continue
                self.sprites.append(img)
                if len(text) == 2 and rng.random() < 0.5:
                    self.sprites.append(_circled(img))

    def draw(self, rng, sq: np.ndarray, ink: float) -> None:
        cell = sq.shape[0]
        sprite = self.sprites[rng.integers(len(self.sprites))]
        scale = rng.uniform(0.2, 0.75) * cell / max(sprite.shape)
        h, w = max(2, int(sprite.shape[0] * scale)), max(2, int(sprite.shape[1] * scale))
        sp = cv2.resize(sprite, (w, h), interpolation=cv2.INTER_AREA)
        oy = int(np.clip((cell - h) // 2 + rng.integers(-cell // 6, cell // 6 + 1), 0, cell - h))
        ox = int(np.clip((cell - w) // 2 + rng.integers(-cell // 6, cell // 6 + 1), 0, cell - w))
        region = sq[oy:oy + h, ox:ox + w]
        np.minimum(region, np.where(sp < 0.6, ink, 1.0), out=region)


def _circled(img: np.ndarray) -> np.ndarray:
    """A square name in a circle, like a chart of the board's squares."""
    side = int(max(img.shape) * 1.6)
    out = np.ones((side, side), np.float32)
    y, x = (side - img.shape[0]) // 2, (side - img.shape[1]) // 2
    out[y:y + img.shape[0], x:x + img.shape[1]] = img
    cv2.circle(out, (side // 2, side // 2), side // 2 - 2, 0.0, max(1, side // 30))
    return out


# ---------------------------------------------------------------- square styles

def dark_texture(rng, size: int) -> np.ndarray:
    kind = rng.choice(["gray", "hatch", "hatch", "cross", "dots", "plain"], p=[0.25, 0.3, 0.1, 0.1, 0.15, 0.1])
    tex = np.ones((size, size), np.float32)
    if kind == "gray":
        tex[:] = rng.uniform(0.55, 0.94)
    elif kind in ("hatch", "cross"):
        spacing = rng.uniform(0.07, 0.18) * size
        width = max(1.0, rng.uniform(0.25, 0.5) * spacing)
        yy, xx = np.mgrid[:size, :size]
        angles = [rng.choice([45, 135])] if kind == "hatch" else [45, 135]
        for a in angles:
            d = (xx + yy) if a == 45 else (xx - yy)
            tex[(d % spacing) < width] = rng.uniform(0.0, 0.35)
    elif kind == "dots":
        density = rng.uniform(0.15, 0.5)
        dots = rng.random((size, size)) < density
        dots = cv2.dilate(dots.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0 if rng.random() < 0.5 else dots
        tex[dots] = rng.uniform(0.0, 0.4)
    return tex


def synth_board(rng, sprites: Sprites, cell: int, marks: Marks | None = None):
    """A random position drawn with one sprite style: image (uint8), frame box, labels."""
    style = sprites.styles[rng.integers(len(sprites.styles))]
    occupancy = rng.uniform(0.1, 0.55)
    weights = np.array([8, 2, 2, 2, 1, 1] * 2, np.float64)
    labels = [int(rng.choice(np.arange(1, 13), p=weights / weights.sum())) if rng.random() < occupancy else 0 for _ in range(64)]
    margin = int(cell * rng.uniform(0.6, 1.4))
    frame = int(rng.integers(1, max(2, cell // 6) + 1))
    size = 8 * cell + 2 * (margin + frame)
    img = np.ones((size, size), np.float32)
    x0 = y0 = margin
    img[y0:size - margin, x0:size - margin] = 0  # frame
    inner = margin + frame
    light_level = rng.uniform(0.93, 1.0)
    shade_dark = rng.random() < 0.95
    tex = dark_texture(rng, cell)
    # A third of the boards mark some empty squares (a few, or whole rows of asterisks).
    mark_rate = rng.choice([0.0, 0.0, rng.uniform(0.03, 0.4)]) if marks else 0.0
    for i, label in enumerate(labels):
        r, c = divmod(i, 8)
        sq = np.full((cell, cell), light_level, np.float32)
        if (r + c) % 2 == 1 and shade_dark:
            sq = tex.copy()
        if not label and rng.random() < mark_rate:
            marks.draw(rng, sq, rng.uniform(0.0, 0.3))
        if label:
            sprite, sil = style[label][rng.integers(len(style[label]))]
            scale = rng.uniform(0.72, 0.95) * cell / max(sprite.shape)
            h, w = max(2, int(sprite.shape[0] * scale)), max(2, int(sprite.shape[1] * scale))
            sp = cv2.resize(sprite, (w, h), interpolation=cv2.INTER_AREA)
            si = cv2.resize(sil.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST) > 0
            oy = (cell - h) // 2 + int(rng.integers(-1, 2))
            ox = (cell - w) // 2 + int(rng.integers(-1, 2))
            oy, ox = max(0, min(cell - h, oy)), max(0, min(cell - w, ox))
            region = sq[oy:oy + h, ox:ox + w]
            region[si] = sp[si] * light_level
        img[inner + r * cell:inner + (r + 1) * cell, inner + c * cell:inner + (c + 1) * cell] = sq
    if rng.random() < 0.05:  # two half-boards in one frame
        x = inner + int(rng.integers(2, 7)) * cell
        width = int(rng.integers(1, max(2, cell // 10) + 1))
        img[inner:inner + 8 * cell, x - width // 2:x - width // 2 + width] = 0
    return (img * 255).astype(np.uint8), (x0, y0, size - margin, size - margin), labels


# ---------------------------------------------------------------- real typed boards

def typed_boards(pdf_path: Path):
    """(page, PDF bbox, placement) of every typed diagram in a book."""
    from cbv.ingest.pdf import PdfBook

    book = PdfBook(pdf_path)
    return [(b.source.page, b.source.bbox, b.placement) for b in book.doc.blocks if b.kind == "diagram" and b.placement]


def render_typed(rng, doc: pymupdf.Document, page: int, bbox, cell: int):
    x0, y0, x1, y1 = bbox
    zoom = cell * 8 / max(x1 - x0, 1) * rng.uniform(0.98, 1.02)
    pad = 6
    clip = pymupdf.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    pix = doc[page].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, colorspace=pymupdf.csGRAY)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
    box = (int(pad * zoom), int(pad * zoom), int((x1 - x0 + pad) * zoom), int((y1 - y0 + pad) * zoom))
    return img, box


# ---------------------------------------------------------------- damage

def degrade(rng, img: np.ndarray) -> np.ndarray:
    f = img.astype(np.float32) / 255
    if rng.random() < 0.3:  # slight rotation
        h, w = f.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-0.8, 0.8), 1.0)
        f = cv2.warpAffine(f, m, (w, h), borderValue=1.0)
    low_res = rng.random() < 0.35
    if low_res:  # low resolution scan
        k = rng.uniform(0.4, 0.7)
        small = cv2.resize(f, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        f = cv2.resize(small, (f.shape[1], f.shape[0]), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.6:  # (milder on top of low resolution: beyond that even a person can't tell)
        f = cv2.GaussianBlur(f, (0, 0), rng.uniform(0.3, 0.7 if low_res else 1.3))
    if rng.random() < 0.5:  # faded ink / gray paper
        lo, hi = rng.uniform(0.0, 0.45), rng.uniform(0.82, 1.0)
        f = lo + (hi - lo) * f
    if rng.random() < 0.5:
        f = f + rng.normal(0, rng.uniform(0.01, 0.07), f.shape).astype(np.float32)
    if rng.random() < 0.12:  # black-and-white scan
        f = (f > rng.uniform(0.45, 0.7)).astype(np.float32)
    out = (np.clip(f, 0, 1) * 255).astype(np.uint8)
    if rng.random() < 0.4:
        _, enc = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(25, 90))])
        out = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE)
    return out


def jitter(rng, box, cell):
    j = max(1, int(cell * 0.12))
    return tuple(int(v + rng.integers(-j, j + 1)) for v in box)


def cells_of(rng, img, box, labels, out_x, out_y, keep_empty: float):
    board = board_from_box(img, jitter(rng, box, (box[2] - box[0]) // 8))
    if board is None:
        return 0
    for cell, label in zip(board.cells, labels):
        if label == 0 and rng.random() > keep_empty:
            continue
        out_x.append((cell * 255).astype(np.uint8))
        out_y.append(label)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--synthetic", type=int, default=4000)
    ap.add_argument("--real", type=int, default=2500)
    ap.add_argument("--woodpecker", type=Path)
    ap.add_argument("--polgar", type=Path)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-marks", action="store_true", help="no marks on empty squares (the data of pieces.onnx)")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)
    xs, ys = [], []

    sprites = Sprites()
    sprites.add_font(DEJAVU, DEJAVU_GLYPHS)
    sources = []
    for path in (args.woodpecker, args.polgar):
        if path:
            doc = pymupdf.open(path)
            boards = typed_boards(path)
            print(f"{path.name}: {len(boards)} typed boards", flush=True)
            sources.append((doc, boards))
            if path == args.polgar:
                font = _extract_font(doc, "SkakNew-Diagram", args.out.parent)
                sprites.add_font(str(font), SKAK_LIGHT)
            else:
                sprites.add_cells(_light_cells(rng, doc, boards[:400]))
    print(f"sprite styles: {len(sprites.styles)}", flush=True)
    marks = None if args.no_marks else Marks(rng)
    if marks:
        print(f"square marks: {len(marks.sprites)}", flush=True)

    made = 0
    while made < args.synthetic:
        cell = int(rng.integers(10, 56))
        img, box, labels = synth_board(rng, sprites, cell, marks)
        made += cells_of(rng, degrade(rng, img), box, labels, xs, ys, keep_empty=0.3)
    print(f"synthetic boards: {made}, squares so far {len(ys)}", flush=True)

    made = 0
    while sources and made < args.real:
        doc, boards = sources[int(rng.integers(len(sources)))]
        page, bbox, placement = boards[int(rng.integers(len(boards)))]
        cell = int(rng.integers(10, 56))
        img, box = render_typed(rng, doc, page, bbox, cell)
        made += cells_of(rng, degrade(rng, img), box, placement_labels(placement), xs, ys, keep_empty=0.25)
    print(f"real boards: {made}, squares {len(ys)}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out, x=np.stack(xs), y=np.array(ys, np.uint8))
    print("class counts:", np.bincount(np.array(ys), minlength=13).tolist())


def _extract_font(doc: pymupdf.Document, name: str, folder: Path) -> Path:
    for pno in range(0, doc.page_count, 10):
        for xref, _ext, _type, basefont, *_ in doc.get_page_fonts(pno):
            if name in basefont:
                _, ext, _, buf = doc.extract_font(xref)
                path = folder / f"{name}.{ext}"
                folder.mkdir(parents=True, exist_ok=True)
                path.write_bytes(buf)
                return path
    raise LookupError(name)


def _light_cells(rng, doc, boards) -> dict[int, list[np.ndarray]]:
    """Clean high-resolution squares of each piece on a light square, cut from real boards."""
    cells: dict[int, list[np.ndarray]] = {}
    for page, bbox, placement in boards:
        img, box = render_typed(rng, doc, page, bbox, 64)
        board = board_from_box(img, box)
        if board is None:
            continue
        for i, label in enumerate(placement_labels(placement)):
            r, c = divmod(i, 8)
            if label and (r + c) % 2 == 0:
                cells.setdefault(label, []).append(board.cells[i])
    return cells


if __name__ == "__main__":
    main()
