"""Chess fonts: diagrams typed as text, and figurines inside move text.

Many digital books draw diagrams with a chess font: each rank is a line of
characters, one per square, plus border characters. Two encodings cover most
fonts:

* the Marroquin family (Chess Merida, Alpha, Leipzig, Cases…, also used by
  Quality Chess books): ``' '``/``'+'`` empty light/dark squares, white pieces
  ``pnbrqk`` on light and ``PNBRQK`` on dark squares, black pieces ``omvtwl`` on
  light and ``OMVTWL`` on dark squares;
* the LaTeX ``skak`` fonts: ``'0'``/``'Z'`` empty light/dark squares, white
  ``KQRBNP`` on light and ``JLSAMO`` on dark, black in lower case.

Every character also tells the colour of its square, so a row only decodes if the
colours alternate exactly like a real board. That check picks the right table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from ..notation.pieces import GLYPH_FIRST

CHESS_FONT = re.compile(
    r"fig|chess|skak|merida|alpha|leipzig|usual|zurich|linares|diagram|cases|condal|kingdom|magnetic|mayan|marroquin",
    re.IGNORECASE,
)

# char -> (piece symbol in FEN or "" for empty, square is dark)
_Table = dict[str, tuple[str, bool]]


def _table(empty_light: str, empty_dark: str, pieces: dict[str, tuple[str, str]]) -> _Table:
    """``pieces`` maps a FEN symbol to its (light-square char, dark-square char)."""
    t: _Table = {empty_light: ("", False), empty_dark: ("", True)}
    for fen, (light, dark) in pieces.items():
        t[light] = (fen, False)
        t[dark] = (fen, True)
    return t


TABLES: dict[str, _Table] = {
    "marroquin": _table(" ", "+", {
        "P": ("p", "P"), "N": ("n", "N"), "B": ("b", "B"), "R": ("r", "R"), "Q": ("q", "Q"), "K": ("k", "K"),
        "p": ("o", "O"), "n": ("m", "M"), "b": ("v", "V"), "r": ("t", "T"), "q": ("w", "W"), "k": ("l", "L"),
    }),
    "skak": _table("0", "Z", {
        "K": ("K", "J"), "Q": ("Q", "L"), "R": ("R", "S"), "B": ("B", "A"), "N": ("N", "M"), "P": ("P", "O"),
        "k": ("k", "j"), "q": ("q", "l"), "r": ("r", "s"), "b": ("b", "a"), "n": ("n", "m"), "p": ("p", "o"),
    }),
}

# Marroquin fonts print rank labels in the left border as 0xC0 (rank 1) .. 0xC7 (rank 8).
_RANK_LABELS = {chr(0xC0 + i): i + 1 for i in range(8)}


def unsymbol(text: str) -> str:
    """Symbol-encoded fonts put their glyphs at U+F020..U+F0FF; map them back to 0x20..0xFF."""
    return "".join(chr(ord(c) - 0xF000) if 0xF020 <= ord(c) <= 0xF0FF else c for c in text)


@dataclass
class TypedRow:
    table: str
    symbols: list[str]  # 8 FEN symbols, "" for empty squares
    first_dark: bool
    label: int | None  # rank printed in the border, if any


def decode_row(text: str) -> TypedRow | None:
    """Decodes one typed rank, or None if the text is not exactly 8 squares of one table."""
    text = unsymbol(text)
    for name, table in TABLES.items():
        squares = [table[c] for c in text if c in table]
        if len(squares) != 8:
            continue
        # Light and dark squares alternate along a rank.
        if any(squares[i][1] == squares[i + 1][1] for i in range(7)):
            continue
        label = next((_RANK_LABELS[c] for c in text if c in _RANK_LABELS), None) if name == "marroquin" else None
        return TypedRow(name, [s[0] for s in squares], squares[0][1], label)
    return None


def placement(rows: list[TypedRow]) -> str | None:
    """FEN piece placement of 8 typed rows (top first), or None if they don't form a board."""
    if len(rows) != 8 or len({r.table for r in rows}) != 1:
        return None
    # The top-left square is light for both orientations (a8 or h1), and colours alternate down the board.
    if rows[0].first_dark or any(rows[i].first_dark == rows[i + 1].first_dark for i in range(7)):
        return None
    symbols = [r.symbols for r in rows]
    if rows[0].label == 1:  # printed from Black's side: rank 1 at the top
        symbols = [list(reversed(r)) for r in reversed(symbols)]
    fen_rows = []
    for row in symbols:
        out, empty = "", 0
        for s in row:
            if s:
                out += (str(empty) if empty else "") + s
                empty = 0
            else:
                empty += 1
        fen_rows.append(out + (str(empty) if empty else ""))
    result = "/".join(fen_rows)
    board = chess.Board(f"{result} w - - 0 1")
    if len(board.pieces(chess.KING, chess.WHITE)) != 1 or len(board.pieces(chess.KING, chess.BLACK)) != 1:
        return None
    return result


# Characters a figurine font may use for notation itself; everything else is a glyph.
_NOTATION = set("abcdefgh0123456789x+#=-–.…()[]!?,;: \n†‡±∓∞")
_FIGURINE_LETTERS = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙"}


class GlyphMapper:
    """Rewrites text set in a figurine font so the tokenizer can read it.

    Letters K Q R B N P become Unicode figurines (fonts that draw figurines on
    those letters mean the English pieces, whatever the book's language), ``X``
    is a capture, and any other character becomes a private-use glyph whose
    meaning the parser works out from legal moves.
    """

    def __init__(self):
        self.glyphs: dict[str, str] = {}

    def figurine_text(self, text: str) -> str:
        out = []
        for c in unsymbol(text):
            if c in _NOTATION:
                out.append(c)
            elif c in _FIGURINE_LETTERS:
                out.append(_FIGURINE_LETTERS[c])
            elif c == "X":
                out.append("x")
            else:
                if c not in self.glyphs:
                    self.glyphs[c] = chr(GLYPH_FIRST + len(self.glyphs))
                out.append(self.glyphs[c])
        return "".join(out)
