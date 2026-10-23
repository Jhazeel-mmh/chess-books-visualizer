"""Finds chess tokens (move numbers, moves, annotation symbols, brackets) in text.

The tokenizer only recognizes shapes. Whether ``Nf3`` is really a move, and which
piece ``R`` means, is decided later by :mod:`cbv.notation.matcher` against a board.
Offsets always refer to the text given to :func:`tokenize`, so callers can map
tokens back to the page or the EPUB node they came from.

Text recognized by OCR gets a more tolerant reading (``ocr=True``): a figurine
comes out as a short run of junk (``l:t``, ``'it>``, ``tLl``), which is kept as
the move's piece symbol for the parser to learn per book, and a rank digit may
have been read as a letter (``eS`` for e5, ``gl`` for g1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from .pieces import PIECE_CHARS

# One-to-one replacements, so offsets in the normalized text match the original.
_NORMALIZE = str.maketrans({
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
})

_GLYPHS = r"-"
_WORD = rf"\w{_GLYPHS}"
_PIECE = rf"{PIECE_CHARS}{_GLYPHS}"
_PROMO = rf"QRBNDTAC♕♖♗♘♛♜♝♞{_GLYPHS}"
_SUFFIX_NAG = r"!!|\?\?|!\?|\?!|!|\?"

_MASTER = re.compile(
    rf"""
    (?P<result>(?<![{_WORD}-])(?:1-0|0-1|½-½|1/2-1/2|½:½)(?![{_WORD}]))
  | (?P<castle>(?<![{_WORD}-])(?P<cside>[O0o]-\s?[O0o](?:-\s?[O0o])?)[+\#‡†]{{0,2}}(?P<cnag>{_SUFFIX_NAG})?(?![{_WORD}-]))
  | (?P<number>(?<![{_WORD}.])(?P<num>\d{{1,3}})(?!\d)(?:(?P<black>\s?\.?\s?(?:\.{{2,3}}|…))|(?P<white>\.))?)
  | (?P<move>(?<![{_WORD}])
        (?P<piece>[{_PIECE}])?(?P<ff>[a-h])?(?P<fr>[1-8])?(?P<cap>[-x:×])?(?P<to>[a-h][1-8])
        (?:=?(?P<promo>[{_PROMO}])|\((?P<promo2>[{_PROMO}])\)|/(?P<promo3>[{_PROMO}]))?
        [+\#‡†]{{0,2}}(?P<mnag>{_SUFFIX_NAG})?[{_GLYPHS}]{{0,2}}(?:\s?e\.\s?p\.)?
        (?![{_WORD}]))
  | (?P<nagsym>[±∓⩲⩱∞□→↑⇆⇄∆△])
  | (?P<nagtxt>(?<![^\s(\[])(?:\+-|-\+|\+/-|-/\+|\+/=|=/\+|\+=|=\+|=|N|{_SUFFIX_NAG})(?![^\s)\],;.]))
  | (?P<open>[(\[])
  | (?P<close>[)\]])
    """,
    re.VERBOSE,
)

NAG_CODES: dict[str, int] = {
    "!": 1, "?": 2, "!!": 3, "??": 4, "!?": 5, "?!": 6, "□": 7, "=": 10, "∞": 13,
    "⩲": 14, "+=": 14, "+/=": 14, "⩱": 15, "=+": 15, "=/+": 15,
    "±": 16, "+/-": 16, "∓": 17, "-/+": 17, "+-": 18, "-+": 19, "N": 146,
}


# OCR mode. Results and castling as printed, with "o" for zero and "l" or "I" for one.
_OCR_MASTER = re.compile(
    rf"""
    (?P<result>(?<![{_WORD}-])(?:[1lI]-[0oO]|[0oO]-[1lI]|½-½|1/2-1/2|½:½)(?![{_WORD}]))
  | (?P<castle>(?<![{_WORD}-])(?P<cside>[O0o]-\s?[O0o](?:-\s?[O0o])?)[+\#‡†]{{0,2}}(?P<cnag>{_SUFFIX_NAG})?(?![{_WORD}-]))
  # A two-digit number split by a space, before its dots: "1 1.0-0" is 11, "2 l ..." 21, "1 O.c4" 10.
  | (?P<split>(?<![^\s(\[])(?P<n1>[1-9lI])\s(?P<n2>[\dlIO])(?![\w:;'!>"])(?P<sdots>(?:\s?[.,·•…]){{1,3}}))
  # "12.", "12", "l ...", "IO.", "2 . .. ": a number made of digits or look-alikes, then up to three dots.
  | (?P<number>(?<![^\s(\[])(?P<num>[1-9lIS][\dlIOS]{{0,2}})(?![\w:;'!>"])(?P<dots>(?:\s?[.,·•…]){{1,3}})?)
  # Anything short before a square counts as the piece; the parser learns what each spelling means.
  # A "[" right after a move number is a figurine ("4.[g5"), not a bracket. A square may be split
  # by a space ("d 5", "!b l") unless its digit is a move number ("d 5." or "d 53").
  | (?P<move>(?<![^\s(\[.,;])
        (?P<pre>(?:(?<=\.)\[(?=x?[a-h]))?[^\s()\[\]]{{0,6}}?)(?P<cap>[x×])?(?P<to>[a-h][1-8SsIilZzBG]|[a-h]\s[1-8lI](?!\s?[.·•…])(?!\d))
        (?:=(?P<promo>[QRBNDTAC]))?(?P<suf>(?:[+\#‡†](?![-=/])){{0,2}}[!?]{{0,2}})
        (?=[\s,;:.)\]=+-]|$))
  | (?P<nagsym>[±∓⩲⩱∞□→↑⇆⇄∆△])
  # An evaluation may follow a move without a space ("Bh6+-").
  | (?P<nagtxt>(?:(?<![^\s(\[])|(?<=[1-8SsIilZzBG]))(?:\+-|-\+|\+/-|-/\+|\+/=|=/\+|\+=|=\+|=|{_SUFFIX_NAG})(?![^\s)\],;.]))
  | (?P<open>[(\[])
  | (?P<close>[)\]])
    """,
    re.VERBOSE,
)
_OCR_DIGITS = str.maketrans("lIOS", "1105")
# OCR may read a figurine as a control character; regular expressions would take some for spaces.
_OCR_CONTROLS = {c: 0x2400 + c for c in range(32) if chr(c) not in "\t\n\r"}
_OCR_RANKS = str.maketrans("SsIilZzBG", "551112286")
# Characters that vary between two prints of the same figurine.
_OCR_NOISE = re.compile(r"[.'\"`´‘’,]")
# A letter-only prefix with a vowel is the start of a word ("blancas", "final"), not a piece.
_PROSE = re.compile(r"[^\W\d_]*[aeiouáéíóúAEIOUÁÉÍÓÚ][^\W\d_]*")
_PIECE_LETTERS = "KQRBNDTAC"


@dataclass(frozen=True)
class ParsedMove:
    """The shape of a printed move; pieces are still raw symbols."""

    piece: str | None = None
    from_file: int | None = None
    from_rank: int | None = None
    capture: bool = False
    to_square: chess.Square | None = None
    promotion: str | None = None
    castle: str | None = None  # "K" (short) or "Q" (long)
    # OCR: the move might be a word ("gal" is a rook to a1 only if the book prints rooks as "g").
    weak: bool = False
    # OCR: a word between two moves too garbled to read ("ltln"), kept as the move it stands for.
    unknown: str | None = None
    # A move the reader entered: played as given (UCI), and only from the position ``before`` (FEN).
    fixed: str | None = None
    before: str | None = None
    # Scans: the piece the printed figurine looks like (by its shape), and whether that is sure.
    seen: int | None = None
    seen_sure: bool = False


@dataclass(frozen=True)
class Token:
    kind: str  # "number" | "move" | "nag" | "open" | "close" | "result"
    start: int
    end: int
    text: str
    number: int | None = None
    # None when OCR'd dots leave room for doubt: two dots mean Black ("21..Wf5"), but "1 ..i.e4" may be
    # White's bishop printed as "..i.". The parser tries Black first.
    black: bool | None = False
    move: ParsedMove | None = None
    nag: int | None = None


def normalize(text: str) -> str:
    return text.translate(_NORMALIZE)


def tokenize(text: str, ocr: bool = False) -> list[Token]:
    if ocr:
        return _tokenize_ocr(text)
    text = normalize(text)
    tokens: list[Token] = []
    for m in _MASTER.finditer(text):
        kind = m.lastgroup
        start, end, raw = m.start(), m.end(), m.group()
        if kind == "number":
            tokens.append(Token("number", start, end, raw, number=int(m["num"]), black=m["black"] is not None))
        elif kind == "castle":
            side = "Q" if m["cside"].count("-") == 2 else "K"
            tokens.append(Token("move", start, end, raw, move=ParsedMove(castle=side)))
            _append_nag(tokens, m["cnag"], end)
        elif kind == "move":
            tokens.append(Token("move", start, end, raw, move=_parsed_move(m)))
            _append_nag(tokens, m["mnag"], end)
        elif kind in ("nagsym", "nagtxt"):
            tokens.append(Token("nag", start, end, raw, nag=NAG_CODES.get(raw)))
        else:
            tokens.append(Token(kind, start, end, raw))
    return tokens


def _tokenize_ocr(text: str) -> list[Token]:
    text = normalize(text).translate(_OCR_CONTROLS)
    tokens: list[Token] = []
    pos = 0
    while (m := _OCR_MASTER.search(text, pos)) is not None:
        kind = m.lastgroup
        pos = m.end()
        start, end, raw = m.start(), m.end(), m.group()
        if kind in ("number", "split"):
            digits, dots = (m["num"], m["dots"]) if kind == "number" else (m["n1"] + m["n2"], m["sdots"])
            tokens.append(Token("number", start, end, raw, number=int(digits.translate(_OCR_DIGITS)), black=_ocr_side(dots)))
        elif kind == "move":
            pre = m["pre"]
            glued = _GLUED_NUMBER.match(pre)
            if glued:
                # "10JWe2": the number's dot read as a "J" ("20J!e5"); the rest is the move.
                n = glued.end()
                tokens.append(Token("number", start, start + n, raw[:n], number=int(glued[1]), black=False))
                pre, start = pre[n:], start + n
            elif _SQUARE_ONLY.fullmatch(pre) and not m["cap"]:
                # "1.e4e6": two pawn moves printed without the space between them.
                first = ParsedMove(to_square=chess.parse_square(pre[0] + pre[1].translate(_OCR_RANKS)))
                tokens.append(Token("move", start, start + 2, raw[:2], move=first))
                pre, start = "", start + 2
            move = _ocr_move(m, pre)
            if move:
                tokens.append(Token("move", start, end, text[start:end], move=move))
                nag = m["suf"].lstrip("+#‡†=")
                _append_nag(tokens, nag if nag in NAG_CODES else None, end)
            else:
                # Not a move ("clave 1" is a word and a number): look again just after its letter.
                pos = m.start("to") + 1
        elif kind == "castle":
            side = "Q" if m["cside"].count("-") == 2 else "K"
            tokens.append(Token("move", start, end, raw, move=ParsedMove(castle=side)))
            _append_nag(tokens, m["cnag"], end)
        elif kind in ("nagsym", "nagtxt"):
            tokens.append(Token("nag", start, end, raw, nag=NAG_CODES.get(raw)))
        else:
            tokens.append(Token(kind, start, end, raw))
    return tokens


def _ocr_side(dots: str | None) -> bool | None:
    """One dot (or none) is White's move, three are Black's; two leave it in doubt."""
    n = sum(dots.count(c) for c in ".,·•") + 3 * dots.count("…") if dots else 0
    return False if n <= 1 else (True if n >= 3 else None)


# A move number glued to the move by its dot read as a "J" ("10JWe2").
_GLUED_NUMBER = re.compile(r"(\d{1,3})J(?=\S)")
# A square on its own, as a "piece" before another square: two moves printed together ("e4e6").
_SQUARE_ONLY = re.compile(r"[a-h][1-8]")


def _ocr_move(m: re.Match, pre: str | None = None) -> ParsedMove | None:
    pre = m["pre"] if pre is None else pre
    cap, suffix = m["cap"], m["suf"]
    file, rank = m["to"][0], m["to"][-1]
    if len(m["to"]) == 3 and not (pre or rank.isdigit()):
        return None  # a rank split off by a space: a digit ("d 5"), or after a piece ("S:h l")
    key = _OCR_NOISE.sub("", pre)
    to_square = chess.parse_square(file + rank.translate(_OCR_RANKS))
    if len(key) == 2 and key[0] in _PIECE_LETTERS and key[1] in "abcdefgh12345678" and rank.isdigit():
        # "Nbd7", "Rac8", "Tad1", "N1d2": a piece letter and the file or rank it comes from (not a word).
        origin = {"from_file": "abcdefgh".index(key[1])} if key[1].isalpha() else {"from_rank": int(key[1]) - 1}
        return ParsedMove(piece=key[0], capture=cap is not None, to_square=to_square, **origin)
    if _PROSE.fullmatch(pre) and len(pre) >= 2:
        return None
    # "las", "del", "es" are words, not a5, d1 or e5 ("eS" is). "gal" is a move only in a book that prints
    # its rooks as "g": such a move is weak, and the matcher takes it only once the parser has learned that.
    weak = rank.islower() and not (cap or suffix or (pre and not pre.isalpha()))
    if weak and not pre:
        return None
    promotion = m["promo"] if chess.square_rank(to_square) in (0, 7) else None
    if not key:
        return ParsedMove(capture=cap is not None, to_square=to_square, promotion=promotion)
    if cap and len(key) == 1 and key in "abcdefgh":
        return ParsedMove(from_file="abcdefgh".index(key), capture=True, to_square=to_square, promotion=promotion)
    return ParsedMove(piece=key, capture=cap is not None, to_square=to_square, weak=weak)


def _parsed_move(m: re.Match) -> ParsedMove:
    to_square = chess.parse_square(m["to"])
    promotion = m["promo"] or m["promo2"] or m["promo3"]
    if chess.square_rank(to_square) not in (0, 7):
        promotion = None  # a glyph after "g7" is an annotation (a font's mate sign), not a promotion
    return ParsedMove(
        piece=m["piece"],
        from_file="abcdefgh".index(m["ff"]) if m["ff"] else None,
        from_rank=int(m["fr"]) - 1 if m["fr"] else None,
        capture=m["cap"] is not None and m["cap"] != "-",
        to_square=to_square,
        promotion=promotion,
    )


def _append_nag(tokens: list[Token], suffix: str | None, end: int) -> None:
    """A suffix like ``!?`` belongs to the move token; record it as a zero-width NAG."""
    if suffix:
        tokens.append(Token("nag", end, end, suffix, nag=NAG_CODES[suffix]))
