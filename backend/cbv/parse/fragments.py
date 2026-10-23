"""Groups tokens into move fragments and structural events.

A fragment is a run of moves with nothing but whitespace, move numbers and
annotation symbols between them, starting at a move number (``12.Nf3``,
``12...Nc6``) or right after an opening bracket (``(Nf6 14.d3)``). Prose ends a
fragment. Fragments and brackets may run on into the next block when the
ingestor says the text continues there (``Block.flow_break`` is False). The
anchoring step later decides which position each fragment starts from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from ..ingest.model import Block, DocStream, MoveFix, TextRef
from ..notation.tokenizer import ParsedMove, Token, tokenize


@dataclass
class FragMove:
    ref: TextRef
    text: str
    move: ParsedMove
    # (move number, black to move) when the book printed a number before this move;
    # black is None when an OCR'd number left the side unclear.
    number: tuple[int, bool | None] | None = None
    nags: list[int] = field(default_factory=list)


@dataclass
class Fragment:
    moves: list[FragMove]
    block: int
    starts_para: bool
    bold: bool
    after_open: bool
    heading: bool
    ocr: bool = False


@dataclass
class Heading:
    block: int
    title: str
    game_header: bool


@dataclass
class Open:
    pass


@dataclass
class Close:
    pass


@dataclass
class Result:
    pass


@dataclass
class Diagram:
    block: int
    placement: str | None
    label: str | None = None
    turn: str | None = None  # "w" or "b" when the book shows the side to move
    # Other likely readings of doubtful squares, for when the book's solution doesn't fit.
    alternatives: dict[int, str] = field(default_factory=dict)


@dataclass
class Ref:
    """A block that starts with a diagram's number, like a solution: "165. Karpov – Shirov", "973)"."""

    label: str


Event = Fragment | Heading | Open | Close | Result | Diagram | Ref

# "973)", "165. Anatoly Karpov…", "4637 1.d4…", or the number alone. OCR reads ")" as "}" too.
# Numbers with two decimals ("2.05", chapter 2, exercise 5) can't be moves, so anything may follow.
_REF = re.compile(r"""^\s*(?:(?P<sub>\d{1,2}\.\d\s?\d)(?!\d)
    | (?P<num>\d{1,4})(?:\s*[)}]|(?P<dot>\.(?=\s+[A-ZÁÉÍÓÚÑ]))|\s*$|\s+(?=1\s*\.)))""", re.VERBOSE)


def events(doc: DocStream) -> list[Event]:
    labels = {b.label for b in doc.blocks if b.kind == "diagram" and b.label}
    scanner = _Scanner(doc.blocks)
    for i, block in enumerate(doc.blocks):
        if block.kind == "diagram":
            scanner.end_flow()
            scanner.out.append(Diagram(i, block.placement, block.label, block.turn, block.alternatives))
            continue
        ref = _ref(block.text, labels, block.ocr)
        if block.kind == "heading":
            scanner.end_flow()
            scanner.out.append(Heading(i, " ".join(block.text.split())[:120], block.game_header))
        elif block.flow_break or ref:
            scanner.end_flow()
        if ref:
            scanner.out.append(Ref(ref))
        scanner.scan(i)
        if block.kind == "heading":
            scanner.end_flow()
    scanner.end_flow()
    return scanner.out


def _starts_line(text: str, start: int, scanned: bool) -> bool:
    """Whether moves at ``start`` begin a paragraph: the block's start, or in a scan (whose lines a
    note and the moves after it share) a line after one that ended a sentence."""
    before = text[:start]
    if not before.strip(" \t\n(["):
        return True
    if not scanned:
        return False
    line_start = before.rfind("\n")
    if line_start < 0 or before[line_start + 1:].strip(" \t(["):
        return False
    return before[:line_start].rstrip().endswith((".", ":", ";", "!", "?", ")"))


def _with_fixes(tokens: list[Token], fixes: list[MoveFix], text: str) -> list[Token]:
    """The block's tokens with the reader's fixes: what lies in a fixed span is replaced (or removed)."""
    if not fixes:
        return tokens
    spans = [(f.start, f.end) for f in fixes if f.end > f.start]
    kept = [t for t in tokens if not any(t.start < b and t.end > a for a, b in spans)]
    for f in fixes:
        if f.uci:
            move = ParsedMove(fixed=f.uci, before=f.before)
            kept.append(Token("move", f.start, f.end, text[f.start:f.end], move=move))
    return sorted(kept, key=lambda t: (t.start, t.end))


_LETTERS = re.compile(r"[^\W\d_]+")
_MIXED_CASE = re.compile(r"[a-z][A-Z]")
_VOWELS = set("aeiouáéíóúAEIOUÁÉÍÓÚ")


def _garbled(word: str) -> bool:
    """An OCR word that may be a move gone unreadable ("ltln", "{cJ#"), not a word of prose."""
    if not 2 <= len(word) <= 8 or any(c.isspace() for c in word) or not any(c.isalnum() for c in word):
        return False
    # A capital after a small letter ("lDo", "tLl") is no word of prose, vowels or not.
    return not (_LETTERS.fullmatch(word) and _VOWELS & set(word) and not _MIXED_CASE.search(word))


def _ref(text: str, labels: set[str], ocr: bool = False) -> str | None:
    m = _REF.match(text)
    if m and m["sub"]:
        sub = m["sub"].replace(" ", "")  # OCR: "2.1 0"
        return sub if sub in labels else None
    if not m or m["num"] not in labels:
        return None
    # "1. Nf3" is a move number followed by a move, not a reference to diagram 1.
    if m["dot"] and any(t.kind == "move" and t.start <= m.end() + 2 for t in tokenize(text[:m.end() + 12], ocr)):
        return None
    return m["num"]


class _Scanner:
    """Walks the tokens of consecutive blocks, emitting events in reading order."""

    def __init__(self, blocks: list[Block]):
        self.blocks = blocks
        self.out: list[Event] = []
        self.moves: list[FragMove] | None = None
        self.after_open = False
        self.number: tuple[int, Token] | None = None  # (block index, token)
        self.pending_open = False
        # One entry per open bracket in this flow: whether an Open event was emitted for it.
        self.brackets: list[bool] = []

    def scan(self, index: int) -> None:
        block = self.blocks[index]
        text = block.text
        prev_end = 0
        tokens = _with_fixes(tokenize(text, block.ocr), block.fixes, text)
        # Text the reader removed (or replaced) reads as blank: never an unreadable move to work out.
        for f in block.fixes:
            text = text[:f.start] + " " * (f.end - f.start) + text[f.end:]
        for t in tokens:
            gap = text[prev_end:t.start]
            word = gap.strip()
            if word and block.ocr and (self.moves or self.number) and t.kind in ("move", "number") and _garbled(word):
                # "3.ltln ltlc6 4.ic4", "l.lDo e6": an unreadable move doesn't end the line (nor keep it
                # from starting); the parser may work it out.
                start = prev_end + gap.index(word)
                self.add_move(index, Token("move", start, start + len(word), word, move=ParsedMove(unknown=word)))
            elif word:
                self.break_fragment()
            prev_end = t.end

            if t.kind == "number":
                self.number = (index, t)
            elif t.kind == "move":
                self.add_move(index, t)
            elif t.kind == "nag":
                if self.moves and t.nag is not None:
                    self.moves[-1].nags.append(t.nag)
            elif t.kind == "open":
                self.flush()
                self.brackets.append(False)
                self.pending_open = True
            elif t.kind == "close":
                self.flush()
                self.pending_open = False
                if self.brackets and self.brackets.pop():
                    self.out.append(Close())
            elif t.kind == "result":
                self.flush()
                self.out.append(Result())
        if text[prev_end:].strip():
            self.break_fragment()

    def end_flow(self) -> None:
        self.break_fragment()
        self.out.extend(Close() for emitted in self.brackets if emitted)
        self.brackets = []

    def break_fragment(self) -> None:
        self.flush()
        self.number = None
        self.pending_open = False

    def add_move(self, index: int, t: Token) -> None:
        number, start = None, t.start
        if self.number:
            num_block, num = self.number
            number = (num.number, num.black)
            if num_block == index:
                start = num.start
        self.number = None
        if t.move.fixed and t.move.before:
            # The reader said where it is played from: that gives its number, printed or not.
            fields = t.move.before.split()
            number = (int(fields[5]) if len(fields) > 5 else 1, fields[1] == "b")
        if self.moves is None:
            if number is None and not self.pending_open:
                return  # a bare move in prose: too easy to confuse with a square name
            if self.pending_open:
                self.brackets[-1] = True
                self.out.append(Open())
            self.moves = []
            self.after_open = self.pending_open
            self.pending_open = False
        block = self.blocks[index]
        move = t.move
        if t.end in block.seen:
            piece, sure = block.seen[t.end]
            move = replace(move, seen=piece, seen_sure=sure)
        self.moves.append(FragMove(TextRef(index, start, t.end), block.text[start:t.end], move, number))

    def flush(self) -> None:
        if not self.moves:
            self.moves = None
            return
        first = self.moves[0].ref
        block = self.blocks[first.block]
        bold = sum(self.blocks[m.ref.block].is_bold(m.ref.start, m.ref.end) for m in self.moves)
        self.out.append(Fragment(
            moves=self.moves,
            block=first.block,
            starts_para=_starts_line(block.text, first.start, block.ocr),
            bold=bold * 2 > len(self.moves),
            after_open=self.after_open,
            heading=block.kind == "heading",
            ocr=block.ocr,
        ))
        self.moves = None
