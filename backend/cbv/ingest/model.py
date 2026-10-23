"""Format-independent view of a book: an ordered list of blocks of text.

Ingestors (EPUB, PDF, later OCR) produce a :class:`DocStream`. The parser only
sees block texts and styles, and reports what it found as character ranges
(:class:`TextRef`); each ingestor turns those back into locations in its format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["para", "heading", "diagram"]


@dataclass
class MoveFix:
    """A move the reader entered where the book prints it, or a false move removed (``uci`` None)."""

    start: int
    end: int  # the same as start when the text there was lost (an OCR scan dropped the move)
    uci: str | None
    before: str | None  # FEN of the position the move is played from
    rect: tuple[float, float, float, float] | None = None  # where it is printed, for the highlight


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    # Character ranges (start, end) printed in bold.
    bold: list[tuple[int, int]] = field(default_factory=list)
    # Ingestor-specific data for mapping character ranges back to the source.
    source: Any = None
    # False when the text runs on from the previous block (PDF lines of one
    # paragraph), so a move sequence may continue across the boundary.
    flow_break: bool = True
    # Headings that name a game ("Karpov – Kasparov, Linares 1993") end the previous game.
    game_header: bool = False
    # Diagrams: FEN piece placement, when the ingestor could read the position.
    placement: str | None = None
    # Diagrams: the number printed next to it ("49", "499)"), which solutions refer to.
    label: str | None = None
    # Diagrams: a stable name for the diagram ("p12:40,300", "text/ch1.html#img/d4.gif") under
    # which the reader's corrections are saved.
    key: str | None = None
    # Diagrams read from an image: certainty of the least certain square (0..1), and the
    # squares worth checking (0 = a8 … 63 = h1). Typed diagrams are exact (confidence 1).
    confidence: float | None = None
    uncertain: list[int] = field(default_factory=list)
    # Diagrams: "w" or "b" when the book marks the side to move next to the board.
    turn: str | None = None
    # Diagrams read from an image: other likely readings of doubtful squares ("." = empty).
    alternatives: dict[int, str] = field(default_factory=dict)
    # Text from OCR (a scanned page): moves are read more tolerantly.
    ocr: bool = False
    # Diagrams: the caption sets a task ("White to play", "Juegan blancas ¿Es tablas?", "Ejercicio"),
    # and the points it is worth ("(3 points)").
    task: bool = False
    points: int | None = None
    # Moves the reader fixed in this block's text (PDF books).
    fixes: list[MoveFix] = field(default_factory=list)
    # Scans: the piece each printed move's figurine looks like, by the end of the move in the text,
    # and whether the shape is sure (see :mod:`cbv.vision.figurines`).
    seen: dict[int, tuple[int, bool]] = field(default_factory=dict)

    def is_bold(self, start: int, end: int) -> bool:
        """True if most of ``text[start:end]`` is bold."""
        covered = sum(max(0, min(end, b) - max(start, a)) for a, b in self.bold)
        return covered * 2 > end - start


@dataclass
class DocStream:
    blocks: list[Block]
    # The book's sections, from its table of contents or chapters: (first block, title).
    sections: list[tuple[int, str]] = field(default_factory=list)


@dataclass(frozen=True)
class TextRef:
    block: int
    start: int
    end: int


@dataclass(frozen=True)
class Mark:
    """Something the reader highlights in the book: a move, an unresolved fragment or a diagram."""

    kind: Literal["move", "unresolved", "diagram"]
    id: str
    ref: TextRef
    # Moves read from damaged text (an OCR guess or repair): shown so that the reader can tell.
    uncertain: bool = False
    # Moves the reader entered (move fixes): shown as such.
    fixed: bool = False
