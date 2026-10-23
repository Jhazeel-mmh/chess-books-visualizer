"""Reading the figurines of a scanned book by their shape.

In a scan with an OCR text layer, a figurine (♘ before "f3") comes out as junk text that changes
from page to page ("T", "tLl", "4J", "ltJ" for the same knight), while the figurine itself is
printed clearly. The moves the parser already linked show what each piece looks like in this book:
their figurines are cropped from the page and labelled with the piece that moved. Every other
printed figurine is then read by its nearest labelled shapes. No model is trained and nothing is
labelled by hand: the book teaches itself.

The shape is a hint for the parser (``Block.seen``): it settles a spelling the parser doesn't know,
and overrides a known one only when it is sure. The reading with shapes is kept only if it links
at least as many moves with the printed checks agreeing as well.
"""

from __future__ import annotations

import math
from pathlib import Path

import chess
import numpy as np

# Pages are rendered at this zoom; each figurine becomes a SIZE x SIZE patch.
ZOOM = 5
SIZE = 20
# The labelled shapes nearest to a figurine vote for its piece.
NEIGHBOURS = 5
# Votes needed for a hint, and for a sure one (which may override a known spelling).
MIN_VOTES = 4
SURE_VOTES = 5
# How alike (correlation) the nearest shapes must be: a letter ("g" printed for a rook) is not a figurine.
MIN_SIMILARITY = 0.55
# Too few labelled shapes (or pieces) to read the others by.
MIN_LABELLED = 100
# A second reading is kept unless the printed checks agree less often by more than chance allows:
# this many standard errors of the first reading's share (at least one point).
PRECISION_SLACK = 1.5

_VERSION = 1


class GlyphImages:
    """Shapes cropped from a PDF's pages, kept between runs in ``cache`` (an .npz file)."""

    def __init__(self, pdf_path: Path, cache: Path | None = None, read_only: bool = False):
        import pymupdf

        self.pdf = pymupdf.open(pdf_path)
        self.cache = cache
        self.read_only = read_only
        self.shapes: dict[str, np.ndarray] = {}
        self.changed = False
        if cache and cache.is_file():
            data = np.load(cache, allow_pickle=False)
            if int(data["version"]) == _VERSION:
                self.shapes = dict(zip(data["keys"].tolist(), data["shapes"]))

    @staticmethod
    def key(page: int, rect: tuple[float, ...]) -> str:
        return f"{page}:" + ",".join(f"{v:.1f}" for v in rect)

    def read(self, wanted: list[tuple[int, tuple[float, ...]]]) -> dict[str, np.ndarray | None]:
        """The shapes at (page, rect), rendering each page needed once."""
        out: dict[str, np.ndarray | None] = {}
        missing: dict[int, list[tuple[float, ...]]] = {}
        for page, rect in wanted:
            k = self.key(page, rect)
            if k in self.shapes:
                out[k] = self.shapes[k] if self.shapes[k].any() else None
            else:
                missing.setdefault(page, []).append(rect)
        for page, rects in sorted(missing.items()):
            image = self._render(page)
            for rect in rects:
                shape = _patch(image, rect)
                k = self.key(page, rect)
                self.shapes[k] = shape if shape is not None else np.zeros(SIZE * SIZE, np.float32)
                out[k] = shape
                self.changed = True
        return out

    def _render(self, page: int) -> np.ndarray:
        import pymupdf

        pix = self.pdf[page].get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM), colorspace=pymupdf.csGRAY)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(np.float32) / 255

    def save(self) -> None:
        if not (self.cache and self.changed and not self.read_only):
            return
        keys = list(self.shapes)
        tmp = self.cache.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, version=_VERSION, keys=np.array(keys), shapes=np.stack([self.shapes[k] for k in keys]))
        tmp.replace(self.cache)


def _patch(image: np.ndarray, rect: tuple[float, ...]) -> np.ndarray | None:
    """The ink inside ``rect`` (PDF points), squared up and scaled to SIZE x SIZE, normalized."""
    x0, y0, x1, y1 = (int(round(v * ZOOM)) for v in rect)
    crop = image[max(0, y0):y1 + 1, max(0, x0):x1 + 1]
    ink = crop < 0.6
    if ink.sum() < 8:
        return None
    ys, xs = np.nonzero(ink)
    crop = crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    side = max(h, w)
    square = np.ones((side, side), np.float32)
    square[(side - h) // 2:(side - h) // 2 + h, (side - w) // 2:(side - w) // 2 + w] = crop
    idx = (np.arange(SIZE) * side / SIZE).astype(int)
    v = 1 - square[np.ix_(idx, idx)]
    return ((v - v.mean()) / (v.std() + 1e-6)).ravel().astype(np.float32)


class FigurineReader:
    """Reads a figurine by the labelled shapes nearest to it."""

    def __init__(self, shapes: np.ndarray, pieces: np.ndarray):
        self.shapes = shapes
        self.pieces = pieces

    def read(self, shape: np.ndarray) -> tuple[int, bool] | None:
        """The piece and whether that is sure, or None when the shape is unlike any figurine or in doubt."""
        similarity = self.shapes @ shape / shape.size
        nearest = np.argsort(-similarity)[:NEIGHBOURS]
        if similarity[nearest].mean() < MIN_SIMILARITY:
            return None
        values, counts = np.unique(self.pieces[nearest], return_counts=True)
        best = counts.argmax()
        if counts[best] < MIN_VOTES:
            return None
        return int(values[best]), bool(counts[best] >= SURE_VOTES)


def _rect(block, start: int, end: int) -> tuple[float, ...] | None:
    boxes = [block.source.boxes[4 * c:4 * c + 4] for c in range(start, end)]
    boxes = [b for b in boxes if not math.isnan(b[0])]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _figurines(doc) -> list[tuple[int, int, int, tuple[float, ...]]]:
    """Every printed move of the scanned text with a piece spelling: (block, move end, page, figurine rect)."""
    from ..notation.tokenizer import tokenize

    found = []
    for i, block in enumerate(doc.blocks):
        if block.kind == "diagram" or not block.ocr or not hasattr(block.source, "boxes"):
            continue
        for t in tokenize(block.text, ocr=True):
            if t.kind != "move" or not t.move.piece or t.move.castle:
                continue
            at = t.text.find(t.move.piece)
            rect = _rect(block, t.start + at, t.start + at + len(t.move.piece)) if at >= 0 else None
            if rect:
                found.append((i, t.end, block.source.page, rect))
    return found


def read_by_shape(book, first, cache: Path | None = None, read_only: bool = False):
    """A second reading of a scanned PDF with each figurine's shape as a hint, if it reads better.

    ``first`` is the analysis without shapes; the better of the two is returned (the book's blocks
    keep the hints only if the second one is).
    """
    from ..parse import analyze

    doc = book.doc
    figurines = _figurines(doc)
    if not figurines or not hasattr(book, "path"):
        return first
    where = {(block, end): (page, rect) for block, end, page, rect in figurines}
    labelled: list[tuple[tuple[int, int], int]] = []
    for game in first.anchored.games:
        for node in game.nodes():
            if node.move is None:
                continue
            board = chess.Board(node.parent.fen)
            piece = board.piece_type_at(node.move.from_square)
            if piece == chess.PAWN or board.is_castling(node.move):
                continue
            labelled += [((ref.block, ref.end), piece) for ref in node.refs
                         if ref not in node.guessed and (ref.block, ref.end) in where]
    if len(labelled) < MIN_LABELLED or len({p for _, p in labelled}) < 4:
        return first

    images = GlyphImages(book.path, cache, read_only)
    shapes = images.read([(page, rect) for _, _, page, rect in figurines])
    images.save()
    shape_of = {k: shapes[GlyphImages.key(*where[k])] for k in where}
    known = [(shape_of[k], p) for k, p in labelled if shape_of[k] is not None]
    if len(known) < MIN_LABELLED:
        return first
    reader = FigurineReader(np.stack([s for s, _ in known]), np.array([p for _, p in known]))
    for (block, end), shape in shape_of.items():
        seen = reader.read(shape) if shape is not None else None
        if seen:
            doc.blocks[block].seen[end] = seen
    second = analyze(doc)
    a, b = first.agreement(), second.agreement()
    better = second.anchored.moves_resolved >= first.anchored.moves_resolved
    if better and a["check_precision"] is not None and b["check_precision"] is not None:
        p = a["check_precision"]
        slack = max(0.01, PRECISION_SLACK * math.sqrt(p * (1 - p) / a["checks"]))
        better = b["check_precision"] >= p - slack
    if better:
        return second
    for block in doc.blocks:
        block.seen.clear()
    return first
