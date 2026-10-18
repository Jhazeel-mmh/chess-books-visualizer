"""Turns a :class:`~cbv.ingest.model.DocStream` into game trees."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from collections import Counter

import chess
from dataclasses import dataclass

from ..ingest.model import DocStream, Mark, TextRef
from ..notation.pieces import FIGURINES, LETTERS, PieceMap, glyph_maps, is_glyph, letter_map, wildcard_map
from .anchoring import Anchored, anchor
from .fragments import Event, Fragment, events

# Fragments used to choose the book's notation before the full run.
SAMPLE_FRAGMENTS = 300
# Rounds of learning the piece spellings of an OCR'd book.
OCR_ROUNDS = 4
_OTHER = {"w": "b", "b": "w"}
# Reasons that put a diagram on the reader's list to check. A solution that doesn't fit is more
# often damaged move text than a misread board, so it counts only for a reading that is itself
# less than SURE; "not_a_position" alone is usually an illustration (two half-boards).
TO_CHECK = {"unread", "fixed", "doubtful"}
SOLUTION_TROUBLE = {"solution_failed", "mate_missed"}
SURE = 0.9
# How much likelier (as a log ratio) the best guess for an unlearned spelling must be than the next.
GUESS_MARGIN = math.log(5)


@dataclass
class Analysis:
    doc: DocStream
    anchored: Anchored
    pieces: PieceMap
    style: str

    def sections(self) -> list[dict]:
        """The book's sections (table of contents, chapters, or else headings), and what each holds."""
        found = self.doc.sections or [
            (i, " ".join(b.text.split())) for i, b in enumerate(self.doc.blocks)
            if b.kind == "heading" and not b.game_header and 3 <= len(b.text.strip()) <= 80
        ]
        return [{"block": i, "title": title, "kind": _section_kind(title)} for i, title in found]

    def diagrams(self) -> list[dict]:
        found = []
        flip = self._markers_inverted()
        sections = self.sections()
        starts = [sec["block"] for sec in sections]
        for i, block in enumerate(self.doc.blocks):
            if block.kind == "diagram":
                node = self.anchored.diagram_nodes.get(i)
                fixed = i in self.anchored.diagram_fixes
                # Linked: the moves say whose turn it is. Otherwise the book's mark, read the book's way.
                turn = node.fen.split()[1] if node else (_OTHER.get(block.turn) if flip else block.turn)
                found.append({
                    "id": f"d{i}",
                    "block": i,
                    "key": block.key,
                    "label": block.label,
                    "placement": self.anchored.diagram_fixes.get(i, block.placement),
                    "turn": turn,
                    "confidence": block.confidence,
                    "uncertain": [] if fixed else block.uncertain,
                    "node": node.id if node else None,
                    "fixed": fixed,
                    "check": (check := self._check(i, block, node, fixed)),
                    "to_check": _to_check(check, block.confidence),
                    **self._problem(i, block, node, sections[k] if (k := bisect_right(starts, i) - 1) >= 0 else None),
                })
        return found

    def _problem(self, i: int, block, node, section: dict | None) -> dict:
        """Whether a diagram is a problem to solve, and where the book's solution to it starts.

        A problem: the caption sets a task, a numbered solution refers to it, or it stands in a
        section of exercises; never in a section of solutions, and only for a legal position.
        """
        kind = section["kind"] if section else None
        placement = self.anchored.diagram_fixes.get(i, block.placement)
        legal = bool(placement) and any(chess.Board(f"{placement} {side} - - 0 1").is_valid() for side in "wb")
        problem = legal and kind != "solutions" and (block.task or i in self.anchored.numbered or kind == "problems")
        return {
            "problem": problem,
            "points": block.points,
            "section": section["title"] if section else None,
            "solution": node.id if problem and node is not None and node.children else None,
        }

    def _markers_inverted(self) -> bool:
        """True if the book's side-to-move marks mostly contradict its solutions (read the other way round)."""
        agree = disagree = 0
        for i, block in enumerate(self.doc.blocks):
            node = self.anchored.diagram_nodes.get(i)
            if block.kind == "diagram" and block.turn and node is not None:
                if node.fen.split()[1] == block.turn:
                    agree += 1
                else:
                    disagree += 1
        return disagree >= 10 and disagree > 2 * agree

    def _check(self, i: int, block, node, fixed: bool) -> list[str]:
        """Why a diagram is worth a look in the reader (empty if there is no reason to doubt it)."""
        if block.placement is None:
            return ["unread"]
        reasons = []
        if fixed:
            reasons.append("fixed")
        elif block.uncertain:
            reasons.append("doubtful")
        if not any(chess.Board(f"{block.placement} {side} - - 0 1").is_valid() for side in "wb"):
            reasons.append("not_a_position")
        if i in self.anchored.diagram_failures:
            reasons.append("solution_failed")
        if node is not None and block.confidence is not None and block.confidence < 1 and _mate_missed(self.doc, node):
            reasons.append("mate_missed")
        return reasons

    def marks(self) -> list[Mark]:
        """Everything the reader highlights in the book, with its location."""
        marks = [
            Mark("move", n.id, ref, ref in n.guessed and ref not in n.fixed, ref in n.fixed)
            for g in self.anchored.games for n in g.nodes() for ref in n.refs
        ]
        marks += [Mark("unresolved", str(i), ref) for i, u in enumerate(self.anchored.unresolved) for ref in u.refs]
        marks += [Mark("diagram", d["id"], TextRef(d["block"], 0, 0)) for d in self.diagrams()]
        return marks

    def to_dict(self) -> dict:
        a = self.anchored
        diagrams = self.diagrams()
        return {
            "notation": self.pieces.describe(),
            "style": self.style,
            "games": [g.to_dict() for g in a.games],
            "unresolved": [u.to_dict() for u in a.unresolved],
            "diagrams": diagrams,
            "sections": self.sections(),
            "stats": {
                "moves_found": a.moves_found,
                "moves_resolved": a.moves_resolved,
                "games": len(a.games),
                "diagrams": len(diagrams),
                "diagrams_read": sum(1 for d in diagrams if d["placement"]),
                "diagrams_to_check": sum(1 for d in diagrams if d["to_check"]),
                "diagrams_fixed": sum(1 for d in diagrams if d["fixed"]),
                "problems": sum(1 for d in diagrams if d["problem"]),
            },
        }


def analyze(doc: DocStream) -> Analysis:
    evs = events(doc)
    frags = [e for e in evs if isinstance(e, Fragment)]
    style = _main_line_style(frags)
    sample = _sample(evs, SAMPLE_FRAGMENTS)

    def score(pm: PieceMap) -> int:
        return anchor(sample, pm, style).moves_resolved

    pieces = max((letter_map(lang) for lang in LETTERS), key=score)
    if _mostly_ocr(frags):
        symbols = Counter(m.move.piece for f in frags for m in f.moves if m.move.piece)
        pieces = _learn_symbols(evs, pieces.lang, style, set(symbols))
        return Analysis(doc, anchor(evs, pieces, style, repair=True), pieces, style)
    glyphs = Counter(m.move.piece for f in frags for m in f.moves if m.move.piece and is_glyph(m.move.piece))
    if glyphs:
        # Let unknown glyphs match any piece; each unambiguous move votes for what its glyph means.
        votes = anchor(evs, wildcard_map(pieces.lang, set(glyphs)), style).glyph_votes
        learned: dict[str, Counter] = {}
        for (glyph, piece_type), n in votes.items():
            learned.setdefault(glyph, Counter())[piece_type] = n
        known = {g: c.most_common(1)[0][0] for g, c in learned.items() if c.total() >= 3}
        # Frequent glyphs the votes could not settle are tried in every remaining assignment.
        unknown = [g for g, _ in glyphs.most_common(5) if g not in known]
        pieces = max([pieces, *glyph_maps(pieces.lang, known, unknown)], key=score)
    return Analysis(doc, anchor(evs, pieces, style), pieces, style)


# Section titles: exercises to solve, and the solutions to them (which come first).
_SOLUTIONS = re.compile(r"\b(?:solutions?|soluci[oó]n|soluciones|answers?|respuestas?)\b", re.IGNORECASE)
_PROBLEMS = re.compile(
    # "Problemas", but not "El problema del bloqueo": the singular names a concept.
    r"\b(?:exercises?|ejercicios?|tests?|problems|problemas|puzzles?|combinations|combinaciones|examen|quiz)\b"
    r"|\bmate (?:in|en)\b",
    re.IGNORECASE,
)


def _section_kind(title: str) -> str | None:
    if _SOLUTIONS.search(title):
        return "solutions"
    return "problems" if _PROBLEMS.search(title) else None


def _to_check(reasons: list[str], confidence: float | None) -> bool:
    if set(reasons) & TO_CHECK:
        return True
    return bool(set(reasons) & SOLUTION_TROUBLE) and confidence is not None and confidence < SURE


def _mate_missed(doc: DocStream, start) -> bool:
    """A move the book prints as mate ("Qh7#") that is no mate on the board, in the lines from ``start``."""
    stack = [start]
    while stack:
        node = stack.pop()
        stack.extend(node.children)
        for ref in node.refs:
            text = doc.blocks[ref.block].text[ref.start:ref.end]
            if text.rstrip("!? .").endswith(("#", "‡", "\ue001")) and not chess.Board(node.fen).is_checkmate():
                return True
    return False


def _mostly_ocr(frags: list[Fragment]) -> bool:
    total = sum(len(f.moves) for f in frags)
    return total > 0 and sum(len(f.moves) for f in frags if f.ocr) * 2 > total


def _learn_symbols(evs: list[Event], lang: str, style: str, symbols: set[str]) -> PieceMap:
    """Learns what each piece spelling of an OCR'd book means ("l:t" a rook, "'it>" a king).

    Every spelling starts as "any piece". A move that only one piece could have
    played votes for its spelling; spellings with clear votes are fixed, which
    makes more moves unambiguous for the next round.
    """
    known: dict[str, int] = {}
    for _ in range(OCR_ROUNDS):
        pieces = PieceMap(lang, {**FIGURINES, **known}, True, frozenset(symbols - known.keys()))
        learned: dict[str, Counter] = {}
        for (symbol, piece_type), n in anchor(evs, pieces, style).glyph_votes.items():
            learned.setdefault(symbol, Counter())[piece_type] += n
        new = {}
        for symbol, votes in learned.items():
            piece_type, n = votes.most_common(1)[0]
            if n >= 2 and n >= 0.75 * votes.total():
                new[symbol] = piece_type
        if not new:
            break
        known.update(new)
    unknown = symbols - known.keys()
    return PieceMap(lang, {**FIGURINES, **known}, True, frozenset(unknown), _guess_symbols(known, unknown))


def _guess_symbols(known: dict[str, int], unknown: set[str]) -> dict[str, int]:
    """Guesses unlearned spellings from the learned ones they resemble ("Ll" like "tLl", a knight).

    A small naive Bayes model over the characters and character pairs of each spelling.
    """
    def features(symbol: str) -> set[str]:
        return set(symbol) | {symbol[i:i + 2] for i in range(len(symbol) - 1)}

    counts: dict[int, Counter] = {}
    for symbol, piece_type in known.items():
        counts.setdefault(piece_type, Counter()).update(features(symbol))
    sizes = {p: sum(1 for t in known.values() if t == p) for p in counts}
    total = sum(sizes.values())
    guesses = {}
    for symbol in unknown:
        scores = sorted(
            (math.log(sizes[p] / total) + sum(math.log((c[f] + 0.5) / (sizes[p] + 1)) for f in features(symbol)), p)
            for p, c in counts.items()
        )
        if len(scores) >= 2 and scores[-1][0] - scores[-2][0] > GUESS_MARGIN:
            guesses[symbol] = scores[-1][1]
    return guesses


def _main_line_style(frags: list[Fragment]) -> str:
    """Books that print the main line in bold get "bold"; the rest "paragraph"."""
    total = sum(len(f.moves) for f in frags)
    bold = sum(len(f.moves) for f in frags if f.bold)
    return "bold" if total and 0.05 < bold / total < 0.95 else "paragraph"


def _sample(evs: list[Event], n: int) -> list[Event]:
    seen = 0
    for i, ev in enumerate(evs):
        if isinstance(ev, Fragment):
            seen += 1
            if seen > n:
                return evs[:i]
    return evs
