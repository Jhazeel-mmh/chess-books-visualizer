"""Reads chess positions from images: boards found, squares classified, rules applied."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .board import FoundBoard, find_boards
from .classify import CLASSES, MODELS, available, probabilities

# Bump when board finding or reading changes, so cached results are recomputed.
VERSION = 4

UNCERTAIN = 0.6  # a square read with less certainty than this is flagged for checking
# Squares read with less certainty than this keep their other likely readings, for the parser to
# try when the book's solution doesn't fit the position (at most ALTERNATIVES each, each at least
# ALTERNATIVE_MIN likely).
DOUBTFUL = 0.9
ALTERNATIVES = 2
ALTERNATIVE_MIN = 0.03
# A second king of one colour is kept when the network is this sure of it: some diagrams show two
# half-boards, or "the king on b2 or h2".
SURE_KING = 0.9


@dataclass
class ReadBoard:
    box: tuple[int, int, int, int]  # inner board area in image pixels
    placement: str  # FEN piece placement
    confidence: float  # certainty of the least certain square, 0..1
    uncertain: list[int] = field(default_factory=list)  # squares to check (0 = a8 … 63 = h1)
    turn: str | None = None  # "w" or "b" when the diagram marks the side to move
    # Doubtful squares: their other likely readings, most likely first ("." = empty).
    alternatives: dict[int, str] = field(default_factory=dict)
    # While the book is being read: the squares and the network's probabilities (not saved).
    cells: np.ndarray | None = field(default=None, repr=False, compare=False)
    probs: np.ndarray | None = field(default=None, repr=False, compare=False)

    def saved(self) -> dict:
        d = asdict(self)
        del d["cells"], d["probs"]
        return d


class BoardCache:
    """Boards already read from a book's images, saved next to the book.

    Re-analysing a book (after a correction or a parser change) then skips the slow
    part. The cache is dropped automatically when the model or this code changes.
    """

    def __init__(self, path: Path | None):
        self.path = path
        self.boards: dict[str, list[dict]] = {}
        # Boards read in this run: still open to the book-level second look (see ``finish``).
        self.fresh: dict[str, list[ReadBoard]] = {}
        if path and path.is_file():
            data = json.loads(path.read_text())
            if data.get("version") == _version():
                self.boards = data["boards"]

    def read(self, key: str, read: Callable[[], list[ReadBoard]]) -> list[ReadBoard]:
        """The boards of one image. Boards read now may still change in ``finish``: use them after it."""
        if key in self.fresh:
            return self.fresh[key]
        if key not in self.boards:
            self.fresh[key] = read()
            return self.fresh[key]
        return [
            ReadBoard(**{**b, "box": tuple(b["box"]), "alternatives": {int(k): v for k, v in b.get("alternatives", {}).items()}})
            for b in self.boards[key]
        ]

    def finish(self) -> None:
        """Reads the boards found in this run with the network that suits this book best."""
        boards = [b for found in self.fresh.values() for b in found if b.cells is not None]
        if boards:
            choose_network(boards)
        for key, found in self.fresh.items():
            self.boards[key] = [b.saved() for b in found]
        self.fresh = {}

    def save(self) -> None:
        self.finish()
        if self.path:
            self.path.write_text(json.dumps({"version": _version(), "boards": self.boards}))


def _version() -> str:
    models = hashlib.sha1(b"".join(MODELS[i].read_bytes() for i in available())).hexdigest()[:12]
    return f"{VERSION}-{models}"


def read_boards(gray: np.ndarray, min_size: int = 64) -> list[ReadBoard]:
    """All boards in a grayscale image (uint8, white paper)."""
    return read_found(gray, find_boards(gray, min_size))


def read_found(gray: np.ndarray, boards: list[FoundBoard]) -> list[ReadBoard]:
    if not boards:
        return []
    probs = probabilities(np.concatenate([b.cells for b in boards]))
    out = []
    for i, b in enumerate(boards):
        p = probs[i * 64:(i + 1) * 64]
        board = ReadBoard(box=b.box, placement="", confidence=0.0, turn=turn_marker(gray, b.box), cells=b.cells, probs=p)
        _settle(board, p)
        out.append(board)
    return out


def choose_network(boards: list[ReadBoard]) -> int:
    """Reads a book's boards with whichever network is less often unsure of a square; returns its index.

    A book prints every piece with the same glyph, so a network that struggles with one of them
    (one took a font's white queen for a black one) is unsure on page after page, while the other
    reads it cleanly. The first network is kept unless another is clearly surer.
    """
    cells = np.concatenate([b.cells for b in boards])
    best, best_unsure = 0, _unsure(boards, np.concatenate([b.probs for b in boards]))
    for model in available()[1:]:
        probs = probabilities(cells, model=model)
        unsure = _unsure(boards, probs)
        if unsure < 0.8 * best_unsure:
            best, best_unsure = model, unsure
            for k, b in enumerate(boards):
                b.probs = probs[k * 64:(k + 1) * 64]
    if best:
        for b in boards:
            _settle(b, b.probs)
    return best


def _unsure(boards: list[ReadBoard], probs: np.ndarray) -> int:
    """How many squares of the boards are read with less certainty than UNCERTAIN."""
    return sum(int((decide(probs[k * 64:(k + 1) * 64])[1] < UNCERTAIN).sum()) for k in range(len(boards)))


def _settle(board: ReadBoard, p: np.ndarray) -> None:
    """Sets what a board shows from its square probabilities."""
    labels, certainty = decide(p)
    board.placement = placement(labels)
    board.confidence = round(float(certainty.min()), 3)
    board.uncertain = [int(s) for s in np.nonzero(certainty < UNCERTAIN)[0]]
    board.alternatives = alternatives(p, labels, certainty)


def alternatives(probs: np.ndarray, labels: np.ndarray, certainty: np.ndarray) -> dict[int, str]:
    """For each doubtful square, the other readings worth trying, most likely first."""
    out = {}
    for s in np.nonzero(certainty < DOUBTFUL)[0]:
        p = _allowed(probs[s], int(s))
        order = [int(c) for c in np.argsort(-p) if c != labels[s] and p[c] / max(p.sum(), 1e-9) >= ALTERNATIVE_MIN]
        if order:
            out[int(s)] = "".join(CLASSES[c] for c in order[:ALTERNATIVES])
    return out


def _allowed(p: np.ndarray, square: int) -> np.ndarray:
    """Class probabilities of one square without the readings a diagram can't show there."""
    p = p.copy()
    if square < 8 or square >= 56:
        p[[CLASSES.index("P"), CLASSES.index("p")]] = 0
    return p


def decide(probs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Labels for 64 squares from class probabilities, respecting what a diagram can show.

    Pawns never stand on the first or last rank, and each side has one king (when the
    classifier sees one at all: pawn-structure diagrams may have none). A second king the
    classifier is sure of stays: some diagrams show two half-boards or two king positions.
    """
    p = probs.copy()
    pawns = [CLASSES.index("P"), CLASSES.index("p")]
    p[:8, pawns] = 0
    p[56:, pawns] = 0
    labels = p.argmax(axis=1)
    for king in (CLASSES.index("K"), CLASSES.index("k")):
        best = int(p[:, king].argmax())
        if p[best, king] < 0.2:
            continue
        sure = p[:, king] / np.maximum(p.sum(axis=1), 1e-9) >= SURE_KING
        others = [s for s in np.nonzero(labels == king)[0] if s != best and not sure[s]]
        labels[best] = king
        for s in others:
            q = p[s].copy()
            q[[CLASSES.index("K"), CLASSES.index("k")]] = 0
            labels[s] = int(q.argmax())
    certainty = p[np.arange(64), labels] / np.maximum(p.sum(axis=1), 1e-9)
    return labels, certainty


def placement(labels: np.ndarray) -> str:
    rows = []
    for r in range(8):
        row, empty = "", 0
        for label in labels[r * 8:(r + 1) * 8]:
            if label == 0:
                empty += 1
            else:
                row += (str(empty) if empty else "") + CLASSES[label]
                empty = 0
        rows.append(row + (str(empty) if empty else ""))
    return "/".join(rows)


def turn_marker(gray: np.ndarray, box: tuple[int, int, int, int]) -> str | None:
    """Side to move from a small square or triangle printed beside the board.

    A filled marker means Black to move and an empty one White; when its fill is
    unclear, a marker near the top means Black and near the bottom White.
    """
    x0, y0, x1, y1 = box
    s = (x1 - x0) / 8
    found = []
    for a, b in ((int(x0 - 1.7 * s), int(x0 - 0.08 * s)), (int(x1 + 0.08 * s), int(x1 + 1.7 * s))):
        a, b = max(0, a), min(gray.shape[1], b)
        if b - a < s * 0.3:
            continue
        strip = gray[max(0, y0):min(gray.shape[0], y1), a:b]
        _, ink = cv2.threshold(strip, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(ink, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if not (0.2 * s <= w <= 0.9 * s and 0.2 * s <= h <= 0.9 * s and 0.7 < w / h < 1.4):
                continue
            corners = len(cv2.approxPolyDP(c, 0.08 * cv2.arcLength(c, True), True))
            if corners not in (3, 4):
                continue  # digits and letters of the coordinates have ragged outlines
            fill = float((ink[y:y + h, x:x + w] > 0).mean())
            found.append((fill, y + h / 2 + max(0, y0)))
    if len(found) != 1:
        return None
    fill, cy = found[0]
    if fill > 0.75:
        return "b"
    if fill < 0.45:
        return "w"
    return "b" if cy < (y0 + y1) / 2 else "w"
