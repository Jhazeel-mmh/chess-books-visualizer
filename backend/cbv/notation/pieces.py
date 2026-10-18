"""Piece symbols: per-language letter sets, Unicode figurines and chess-font glyphs.

A book prints pieces as letters (``N`` in English, ``C`` in Spanish), as Unicode
figurines (``♘``), or as glyphs of an embedded chess font. Ingestion maps every
chess-font glyph to a Private Use Area codepoint, so all three cases end up as
single characters that a :class:`PieceMap` resolves to python-chess piece types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import permutations

import chess

FIGURINES: dict[str, chess.PieceType] = {
    "♔": chess.KING, "♚": chess.KING,
    "♕": chess.QUEEN, "♛": chess.QUEEN,
    "♖": chess.ROOK, "♜": chess.ROOK,
    "♗": chess.BISHOP, "♝": chess.BISHOP,
    "♘": chess.KNIGHT, "♞": chess.KNIGHT,
    "♙": chess.PAWN, "♟": chess.PAWN,
}

LETTERS: dict[str, dict[str, chess.PieceType]] = {
    "en": {"K": chess.KING, "Q": chess.QUEEN, "R": chess.ROOK, "B": chess.BISHOP, "N": chess.KNIGHT, "P": chess.PAWN},
    "es": {"R": chess.KING, "D": chess.QUEEN, "T": chess.ROOK, "A": chess.BISHOP, "C": chess.KNIGHT, "P": chess.PAWN},
}

# Ingestion maps chess-font glyphs (and inline figurine images) into this range.
GLYPH_FIRST = 0xE000
GLYPH_LAST = 0xF8FF

# Every character the tokenizer may read as a piece, whatever the book's language.
PIECE_CHARS = "".join(sorted({c for m in LETTERS.values() for c in m})) + "".join(FIGURINES)

PIECE_ORDER = (chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)


def is_glyph(ch: str) -> bool:
    return len(ch) == 1 and GLYPH_FIRST <= ord(ch) <= GLYPH_LAST


@dataclass(frozen=True)
class PieceMap:
    """Resolves piece symbols of one book to piece types."""

    lang: str
    symbols: dict[str, chess.PieceType] = field(hash=False)
    has_glyphs: bool = False
    # Glyphs of unknown meaning that may stand for any piece but a pawn (used to learn them).
    wildcards: frozenset[str] = frozenset()
    # Best guesses for some wildcards, only used to choose between legal moves.
    hints: dict[str, chess.PieceType] = field(default_factory=dict, hash=False)

    def piece(self, symbol: str) -> chess.PieceType | None:
        return self.symbols.get(symbol)

    def describe(self) -> dict:
        glyphs = {f"U+{ord(s):04X}": chess.piece_symbol(p).upper() for s, p in self.symbols.items() if is_glyph(s)}
        out = {"lang": self.lang, "glyphs": glyphs}
        # OCR'd books: how the book's junk spellings of pieces were read ("l:t" → R).
        spellings = {s: chess.piece_symbol(p).upper() for s, p in self.symbols.items() if s not in FIGURINES and not is_glyph(s)}
        if spellings or self.hints:
            out["ocr"] = {"learned": spellings, "guessed": {s: chess.piece_symbol(p).upper() for s, p in self.hints.items()},
                          "unknown": len(self.wildcards) - len(self.hints)}
        return out


def letter_map(lang: str, glyphs: dict[str, chess.PieceType] | None = None) -> PieceMap:
    return PieceMap(lang, {**FIGURINES, **LETTERS[lang], **(glyphs or {})}, bool(glyphs))


def wildcard_map(lang: str, glyphs: set[str]) -> PieceMap:
    return PieceMap(lang, {**FIGURINES, **LETTERS[lang]}, True, frozenset(glyphs))


def glyph_maps(lang: str, known: dict[str, chess.PieceType], unknown: list[str]) -> list[PieceMap]:
    """Every assignment of the still-unknown glyphs to the pieces not yet taken."""
    free = [p for p in PIECE_ORDER if p not in known.values()]
    return [letter_map(lang, {**known, **dict(zip(unknown, perm))}) for perm in permutations(free, min(len(unknown), len(free)))]
