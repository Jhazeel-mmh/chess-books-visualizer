"""Attaches move fragments to game trees.

Each fragment is tried against every position with the right move number and
side to move. The candidate where the most moves turn out legal wins; ties go to
the most plausible context (the line being read, the main line, then the most
recently written position).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from itertools import combinations

import chess

from ..ingest.model import TextRef
from ..notation.matcher import candidates as legal_candidates
from ..notation.matcher import lookalikes
from ..notation.pieces import PieceMap
from ..notation.tokenizer import ParsedMove
from . import decoder
from .fragments import Close, Diagram, Event, FragMove, Fragment, Heading, Open, Ref, Result
from .games import Game, Node, _Ids

MAX_CANDIDATES = 40
RETURN_TO_OPEN_ENDS = True
# An unreadable OCR move is worked out from the moves after it: how many to look at, and how
# many must follow from the chosen move (and from no other).
BRIDGE_LOOKAHEAD = 6
BRIDGE_MIN = 2
# A diagram is corrected from its solution by trying other readings of its doubtful squares (at
# most this many squares, one or two changed at a time).
FIX_SQUARES = 8
# After a fragment from a diagram failed, fragments up to this many moves later continue it.
CONTINUATION_MOVES = 3
# OCR repairs: look-alike characters undone per fragment ("e4" read for "c4"), how far back
# from where the fragment broke to look for them, and the moves each one must make legal.
# Working a fragment out move by move (OCR) must read at least this many moves more than the repairs.
DECODE_GAIN = 2
# Picking a broken main line up again: the next fragment must be read this far (or to its end)…
RESYNC_MOVES = 2
# …and at most this many unread moves are carried over from the fragments before it.
MAX_TAIL = 16
MAX_REPAIRS = 2
REPAIR_WINDOW = 10
REPAIR_GAIN = 2


@dataclass
class Unresolved:
    refs: list[TextRef]
    text: str
    reason: str  # "no_game" | "no_position" | "illegal" | "ambiguous" | "number"

    def to_dict(self) -> dict:
        return {"refs": [[r.block, r.start, r.end] for r in self.refs], "text": self.text, "reason": self.reason}


@dataclass
class Anchored:
    games: list[Game] = field(default_factory=list)
    unresolved: list[Unresolved] = field(default_factory=list)
    # Diagram block -> the node whose position the diagram shows.
    diagram_nodes: dict[int, Node] = field(default_factory=dict)
    moves_found: int = 0
    moves_resolved: int = 0
    # (wildcard glyph, piece type it turned out to move): how the book's chess-font glyphs are learned.
    glyph_votes: Counter = field(default_factory=Counter)
    # Diagram block -> the placement its solution showed it must be (one or two squares misread).
    diagram_fixes: dict[int, str] = field(default_factory=dict)
    # Diagrams whose solution (the first moves tried from them) could not be played.
    diagram_failures: set[int] = field(default_factory=set)
    # Diagrams a numbered solution refers to ("165. Karpov – Shirov"): the book treats them as problems.
    numbered: set[int] = field(default_factory=set)


@dataclass
class _Trial:
    parent: Node
    moves: list[chess.Move]
    reason: str | None
    # Indexes of moves worked out rather than read: a look-alike repair, an unreadable word,
    # or a spelling the parser could only guess.
    guessed: set[int] = field(default_factory=set)


def anchor(events: list[Event], pieces: PieceMap, style: str, repair: bool = False) -> Anchored:
    """``repair`` lets OCR'd fragments undo look-alike characters that made them illegal."""
    return _Anchorer(pieces, style, repair).run(events)


class _Anchorer:
    def __init__(self, pieces: PieceMap, style: str, repair: bool = False):
        self.pieces = pieces
        self.repair = repair
        self.style = style  # "bold" or "paragraph": which signal marks main-line moves
        self.ids = _Ids()
        self.out = Anchored()
        self.game: Game | None = None
        self.cursor: Node | None = None
        self.stack: list[Node | None] = []
        self.new_game_pending = True
        self.pending_title: str | None = None
        # The last diagram with a readable position, until a fragment has been placed after it.
        self.diagram: Diagram | None = None
        # True when that diagram was named by a reference ("165. …"), not just printed before the moves.
        self.diagram_from_ref = False
        # The move number of the first fragment tried from that diagram: a fragment a few moves later
        # ("2 Kh2" after an unreadable "1 Bd5+") continues that solution, so it can't start at the diagram.
        self.diagram_number: tuple[int, bool | None] | None = None
        self.labels: dict[str, Diagram] = {}
        # Scans: the moves of a main-line fragment left unread where it broke off at the end of the game's
        # line (the node), to be worked out together with the next main-line fragment (see ``resync``).
        self.tail: tuple[Node, list[FragMove]] | None = None

    def run(self, events: list[Event]) -> Anchored:
        for ev in events:
            if isinstance(ev, Heading):
                self.new_game_pending = True
                self.pending_title = ev.title
                if ev.game_header:
                    self.game, self.cursor, self.stack, self.tail = None, None, [], None
                    if not self.diagram_from_ref:
                        self.diagram = None
            elif isinstance(ev, Diagram):
                if ev.label:
                    self.labels[ev.label] = ev
                if ev.placement:
                    self.diagram, self.diagram_from_ref, self.diagram_number = ev, False, None
            elif isinstance(ev, Ref):
                target = self.labels.get(ev.label)
                if target is not None and target.placement:
                    self.diagram, self.diagram_from_ref, self.diagram_number = target, True, None
                    self.out.numbered.add(target.block)
            elif isinstance(ev, Result):
                self.new_game_pending = True
            elif isinstance(ev, Open):
                self.stack.append(self.cursor)
            elif isinstance(ev, Close):
                if self.stack:
                    self.cursor = self.stack.pop()
            elif isinstance(ev, Fragment):
                self.out.moves_found += len(ev.moves)
                self.place(ev)
        self.link_diagrams([ev for ev in events if isinstance(ev, Diagram)])
        # A diagram whose first fragment failed may still have been reached by the moves.
        self.out.diagram_failures -= self.out.diagram_nodes.keys()
        return self.out

    def link_diagrams(self, diagrams: list[Diagram]) -> None:
        """Links each diagram not yet placed to a node showing exactly its position."""
        by_placement: dict[str, Node] = {}
        for game in self.out.games:
            for node in game.nodes():
                by_placement.setdefault(node.fen.split()[0], node)
        for d in diagrams:
            placement = self.placement(d)
            if placement and d.block not in self.out.diagram_nodes and placement in by_placement:
                self.out.diagram_nodes[d.block] = by_placement[placement]

    def place(self, frag: Fragment) -> None:
        main_style = frag.heading or (frag.bold if self.style == "bold" else frag.starts_para)
        moves = frag.moves
        if self.tail and main_style and frag.ocr and self.repair:
            done = self.resync(frag)
            if done is not None:
                if not done:
                    return
                moves = done
        bare_start = moves[0].number is None
        while moves:
            self.maybe_start_game(moves[0])
            parents = self.candidates(moves[0], bare_start, main_style, frag.after_open) if self.game else []
            roots = self.diagram_roots(moves[0])
            if roots:
                # A diagram showing a position already in the game stays in that game.
                same = [p for p in parents if p.fen.split()[0] == self.placement(self.diagram)]
                parents = same + roots + [p for p in parents if p not in same]
            # A move the reader fixed brings its own position: if the game has no node there, a line starts at it.
            fixed_root = None
            if moves[0].move.fixed and moves[0].move.before:
                board = chess.Board(moves[0].move.before)
                if not any(p.fen.split()[:2] == moves[0].move.before.split()[:2] for p in parents):
                    fixed_root = Node("pending", None, None, None, board.fen(), 0)
                    parents = parents + [fixed_root]
            if not parents and self.game is None:
                self.unresolve(moves, "no_game")
                return

            trials = [self.trial(p, moves, frag.ocr) for p in parents]
            best = max(trials, key=lambda t: len(t.moves), default=None)  # max() keeps the first of equals
            if frag.ocr and self.repair and roots:
                # A diagram printed just before the moves says where they start: in a scan, read them
                # from it as well as possible before letting them go anywhere else in the game.
                from_diagram = max((t for t in trials if any(t.parent is r for r in roots)), key=lambda t: len(t.moves))
                if from_diagram.reason in ("illegal", "ambiguous"):
                    from_diagram = self.repaired(from_diagram, moves)
                    if from_diagram.reason is not None:
                        from_diagram = self.decoded(from_diagram, moves)
                if len(from_diagram.moves) >= min(2, len(moves)) and (best.reason or len(from_diagram.moves) >= len(best.moves)):
                    best = from_diagram
            if best is not None and best.reason in ("illegal", "ambiguous") and frag.ocr and self.repair:
                best = self.repaired(best, moves)
                if best.reason is not None:
                    best = self.decoded(best, moves)
            if roots and self.diagram.alternatives and (best is None or best.reason or not _mates_hold(best, moves)):
                fixed = self.corrected_diagram(moves, roots, len(best.moves) if best else 0, frag.ocr)
                if fixed is not None:
                    best = fixed
                    roots.append(fixed.parent)
            if roots and self.diagram is not None and not (best is not None and best.moves):
                self.out.diagram_failures.add(self.diagram.block)
            bare_start = False
            if best is not None and best.moves and fixed_root is not None and best.parent is fixed_root:
                best.parent = self.start_game_at(fixed_root.fen)
            if best is not None and best.moves and self.diagram is not None:
                if any(best.parent is root for root in roots):
                    best.parent = self.start_game_at(best.parent.fen)
                if best.parent.fen.split()[0] == self.placement(self.diagram):
                    self.out.diagram_nodes[self.diagram.block] = best.parent
                self.diagram, self.diagram_from_ref = None, False
            if best is None or not best.moves:
                reason = best.reason if best else "no_position"
                j = _next_numbered(moves, 1)
                self.unresolve(moves[:j], reason)
                if main_style and moves is frag.moves:
                    self.extend_tail(frag)
                moves = moves[j:]
                continue

            k = len(best.moves)
            if main_style:
                self.tail = None
            self.cursor = self.apply(best.parent, moves[:k], best.moves, main_style, best.guessed)
            self.out.moves_resolved += k
            if k == len(moves):
                return
            if main_style and frag.ocr and self.repair and not self.cursor.children:
                # The main line broke off here: what is left may be read with the next fragment.
                self.tail = (self.cursor, list(moves[k:]))
            # Re-place the rest from the next printed move number; what lies before it is unresolved.
            j = k if moves[k].number is not None else _next_numbered(moves, k + 1)
            if j > k:
                self.unresolve(moves[k:j], best.reason or "illegal")
            moves = moves[j:]

    def maybe_start_game(self, first: FragMove) -> None:
        if self.game is not None and not self.new_game_pending:
            return
        if first.number not in ((1, False), (1, None)):
            return
        # In a scan the first move may be garbled ("1.e4e6"): a game starts if some first move fits it.
        if legal_candidates(chess.Board(), first.move, self.pieces) or (self.repair and decoder.plausible_start(self.pieces, first)):
            self.start_game_at(chess.STARTING_FEN)

    def diagram_roots(self, first: FragMove) -> list[Node]:
        """The pending diagram as the starting position for this fragment's first move.

        Two positions when an OCR'd number leaves the side in doubt: "21..Wf5" is Black's move,
        but "1 ..i.e4" may be White's bishop printed as "..i.". The side the diagram shows
        comes first, else Black (two dots mean Black).
        """
        if self.diagram is None or first.number is None:
            return []
        number, black = first.number
        if self.diagram_number is None:
            self.diagram_number = first.number
        elif 0 < number - self.diagram_number[0] <= CONTINUATION_MOVES:
            return []
        if black is None:
            black_first = self.diagram.turn != "w"
            sides = [black_first, not black_first]
        else:
            sides = [black]
        roots = []
        for side in sides:
            board = chess.Board(f"{self.placement(self.diagram)} {'b' if side else 'w'} KQkq - 0 {number}")
            board.castling_rights = board.clean_castling_rights()
            if board.is_valid():  # not if the side not to move would be in check
                roots.append(Node("pending", None, None, None, board.fen(), 0))
        return roots

    def beyond_main_line(self, first: FragMove) -> bool:
        """Whether the fragment's first move comes after the end of the game's main line."""
        end = self.game.mainline()[-1]
        board = chess.Board(end.fen)
        end_ply = 2 * (board.fullmove_number - 1) + (board.turn == chess.BLACK)
        number, black = first.number
        ply = 2 * (number - 1) + (1 if black else 0)
        return ply > end_ply

    def start_game_at(self, fen: str) -> Node:
        game = Game(f"g{len(self.out.games) + 1}", self.pending_title, fen, self.ids)
        self.out.games.append(game)
        self.game, self.cursor, self.stack, self.tail = game, game.root, [], None
        self.new_game_pending = False
        self.pending_title = None
        return game.root

    def candidates(self, first: FragMove, bare_start: bool, main_style: bool, after_open: bool = False) -> list[Node]:
        if bare_start:
            # "(Nf6 14.d3)": an alternative to the move just played, or its continuation.
            return [n for n in (self.cursor.parent, self.cursor) if n is not None] if self.cursor else []
        number, black = first.number
        sides = (not black,) if black is not None else (False, True)  # in doubt, Black first
        nodes = [n for side in sides for n in self.game.index.get((number, side), [])]
        if not nodes:
            return []
        if self.repair and main_style and self.tail is not None and self.beyond_main_line(first):
            # A scan whose main line broke off (its unread tail waits): main-line moves printed further
            # on belong to the part that is missing, not to a side line that happens to reach their number.
            return []
        on_path = {id(n) for n in self.cursor.path()} if self.cursor else set()
        on_main = {id(n) for n in self.game.mainline()}

        def rank(n: Node):
            path, main = id(n) not in on_path, id(n) not in on_main
            return (main, path, -n.order) if main_style else (path, main, -n.order)

        ranked = sorted(nodes, key=rank)
        top = ranked[0]
        cursor = self.cursor
        if (RETURN_TO_OPEN_ENDS and not after_open and cursor is not None and top.children
                and top is not cursor and top is not cursor.parent and id(top) in on_path):
            # The text went back past the move just read ("36.Bxc6! 36.hxg4 fxg4 37.Bxc6 … 36...Kg7"):
            # the line it resumes is one still waiting for this move, not the variation just read.
            open_ends = [n for n in ranked if not n.children]
            ranked = open_ends + [n for n in ranked if n.children]
        return ranked[:MAX_CANDIDATES]

    def trial(self, parent: Node, moves: list[FragMove], ocr: bool = False,
              fixes: dict[int, ParsedMove] | None = None) -> _Trial:
        board = parent.board()
        played: list[chess.Move] = []
        guessed: set[int] = set()
        for i, fm in enumerate(moves):
            if fm.number is not None and not _number_fits(fm.number, board, lenient=ocr and i > 0):
                return _Trial(parent, played, "number", guessed)
            found = legal_candidates(board, fixes.get(i, fm.move) if fixes else fm.move, self.pieces)
            if fm.move.unknown is not None:
                # Even a forced move needs the next moves to confirm the word was a move at all ("0-I").
                found = self.bridge(board, moves[i + 1:], found)
            if len(found) != 1:
                return _Trial(parent, played, "ambiguous" if found else "illegal", guessed)
            if (fixes and i in fixes) or fm.move.unknown is not None or fm.move.piece in self.pieces.wildcards:
                guessed.add(i)
            played.append(found[0])
            board.push(found[0])
        return _Trial(parent, played, None, guessed)

    def corrected_diagram(self, moves: list[FragMove], roots: list[Node], have: int, ocr: bool) -> _Trial | None:
        """The pending diagram read differently on one or two doubtful squares, if its solution shows how.

        Accepted only if exactly one such reading lets the whole fragment be played (with every
        printed mate a mate), and that is at least two moves, or one move that mates.
        """
        d = self.diagram
        options = [(s, c) for s in sorted(d.alternatives)[:FIX_SQUARES] for c in d.alternatives[s]]
        changes = [[o] for o in options] + [[a, b] for a, b in combinations(options, 2) if a[0] != b[0]]
        fits: dict[str, _Trial] = {}
        for change in changes:
            for root in roots:
                board = root.board()
                for square, symbol in change:
                    board.set_piece_at(_square(square), None if symbol == "." else chess.Piece.from_symbol(symbol))
                board.castling_rights = board.clean_castling_rights()
                if not board.is_valid():
                    continue
                t = self.trial(Node("pending", None, None, None, board.fen(), 0), moves, ocr)
                if t.reason is None and len(t.moves) > have and _mates_hold(t, moves):
                    printed_mate = any(_printed_mate(fm.text) for fm in moves)
                    if len(t.moves) >= 2 or printed_mate:
                        fits.setdefault(board.board_fen(), t)
        if len(fits) != 1:
            return None
        placement, t = next(iter(fits.items()))
        self.out.diagram_fixes[d.block] = placement
        return t

    def placement(self, d: Diagram) -> str | None:
        """The diagram's position, as corrected from its solution if it had to be."""
        return self.out.diagram_fixes.get(d.block, d.placement)

    def bridge(self, board: chess.Board, rest: list[FragMove], options: list[chess.Move]) -> list[chess.Move]:
        """The one move for an unreadable ply after which the moves printed next can be played.

        Each option is followed by as many of the next moves as stay legal and unambiguous; the
        option that goes furthest wins, if no other goes as far and it carries at least BRIDGE_MIN
        (one for a forced move).
        """
        reach = []
        for move in options:
            b = board.copy(stack=False)
            b.push(move)
            n = 0
            for fm in rest[:BRIDGE_LOOKAHEAD]:
                if fm.move.unknown is not None or (fm.number is not None and not _number_fits(fm.number, b, lenient=True)):
                    break
                found = legal_candidates(b, fm.move, self.pieces)
                if len(found) != 1:
                    break
                b.push(found[0])
                n += 1
            reach.append(n)
        best = max(reach, default=0)
        # A forced move needs one move after it to show the word was a move; a choice needs more.
        need = 1 if len(options) == 1 else BRIDGE_MIN
        return [options[reach.index(best)]] if best >= need and reach.count(best) == 1 else []

    def repaired(self, trial: _Trial, moves: list[FragMove]) -> _Trial:
        """The trial with up to MAX_REPAIRS look-alike characters undone, if that makes enough moves legal.

        "2.e4 e6 3.Nf3 b6 4.Ne3" breaks at Ne3; reading "e4" as "c4" and "Ne3" as "Nc3" lets
        the rest of the game follow, which is the evidence that both were misread.
        """
        stop = len(trial.moves)
        best = trial
        beam: list[dict[int, ParsedMove]] = [{}]
        for depth in range(1, MAX_REPAIRS + 1):
            scored = []
            for fixes in beam:
                for j in range(min(stop, len(moves) - 1), max(-1, stop - REPAIR_WINDOW), -1):
                    if j in fixes:
                        continue
                    for alt in lookalikes(moves[j].move):
                        tried = {**fixes, j: alt}
                        t = self.trial(trial.parent, moves, True, tried)
                        scored.append((len(t.moves), tried, t))
                        if len(t.moves) - stop >= REPAIR_GAIN * depth and len(t.moves) > len(best.moves):
                            best = t
            scored.sort(key=lambda x: -x[0])
            beam = [fixes for n, fixes, _ in scored[:2] if n > stop]
            if not beam or best.reason is None:
                break
        return best

    def resync(self, frag: Fragment) -> list[FragMove] | None:
        """The main line picked up again where it broke off, reading its unread tail with this fragment.

        "7.Bd3 'eNe7 8.Bf4 g5" breaks at the garbled 7...Qc7, which "8.Bf4 g5" alone can't decide;
        "9.Bg3 Bg7 10.Qe2 Ne7" in the next fragment can. Only tried when the game has no position
        at this fragment's move number. Returns None if it didn't work, else this fragment's moves
        left to place (empty when all were read).
        """
        node, tail = self.tail
        first = frag.moves[0]
        if first.number is None or self.game is None or node.parent is None and node is not self.game.root:
            return None
        number, black = first.number
        sides = (black,) if black is not None else (False, True)
        if any(self.game.index.get((number, side)) for side in sides):
            return None  # the fragment has a place to go already
        moves = tail + frag.moves
        found = decoder.decode(self.pieces, node.board(), moves, _number_fits, strict={0, len(tail)})
        if len(found.moves) < len(tail) + min(RESYNC_MOVES, len(frag.moves)):
            return None
        k = len(found.moves)
        self.reclaim(tail)
        self.tail = None
        self.cursor = self.apply(node, moves[:k], found.moves, True, found.guessed)
        self.out.moves_resolved += k
        rest = moves[k:]
        if rest and not self.cursor.children:
            self.tail = (self.cursor, list(rest))
        return rest

    def extend_tail(self, frag: Fragment) -> None:
        """A main-line fragment that found no place joins the unread tail, if it follows on from it."""
        if self.tail is None or not frag.ocr or not self.repair:
            return
        node, tail = self.tail
        first = frag.moves[0]
        board = node.board()
        ply = 2 * (board.fullmove_number - 1) + (board.turn == chess.BLACK) + len(tail)
        if first.number is not None and first.number[1] is not None:
            expected = 2 * (first.number[0] - 1) + first.number[1]
            if abs(expected - ply) <= 1 and len(tail) + len(frag.moves) <= MAX_TAIL:
                self.tail = (node, tail + list(frag.moves))
                return
        self.tail = None

    def reclaim(self, moves: list[FragMove]) -> None:
        """Moves given up as unresolved that were read after all."""
        refs = {fm.ref for fm in moves}
        kept = []
        for u in self.out.unresolved:
            left = [r for r in u.refs if r not in refs]
            if len(left) == len(u.refs):
                kept.append(u)
            elif left:
                kept.append(Unresolved(left, u.text, u.reason))
        self.out.unresolved = kept
        # Words taken off the count of moves when they were given up ("ltln"), now read as moves.
        self.out.moves_found += sum(1 for fm in moves if fm.move.weak or fm.move.unknown is not None)

    def decoded(self, trial: _Trial, moves: list[FragMove]) -> _Trial:
        """The fragment worked out move by move (see :mod:`.decoder`), if that reads it further."""
        found = decoder.decode(self.pieces, trial.parent.board(), moves, _number_fits)
        if len(found.moves) < len(trial.moves) + DECODE_GAIN:
            return trial
        reason = None if len(found.moves) == len(moves) else "illegal"
        return _Trial(trial.parent, found.moves, reason, found.guessed)

    def apply(self, parent: Node, frag_moves: list[FragMove], moves: list[chess.Move], main_style: bool,
              guessed: set[int] = frozenset()) -> Node:
        node = parent
        for i, (fm, move) in enumerate(zip(frag_moves, moves)):
            if fm.move.piece in self.pieces.wildcards:
                self.out.glyph_votes[fm.move.piece, node.board().piece_type_at(move.from_square)] += 1
            child = next((c for c in node.children if c.move == move), None) or self.game.add_child(node, move)
            child.refs.append(fm.ref)
            if i in guessed:
                child.guessed.add(fm.ref)
            if fm.move.fixed:
                child.fixed.add(fm.ref)
            child.nags.update(fm.nags)
            child.votes += main_style
            node = child
        return node

    def unresolve(self, moves: list[FragMove], reason: str) -> None:
        # An OCR word that only might have been a move ("las", "ltln") was most likely just a word.
        words = sum(1 for m in moves if m.move.weak or m.move.unknown is not None)
        if words:
            self.out.moves_found -= words
            moves = [m for m in moves if not (m.move.weak or m.move.unknown is not None)]
        if moves:
            text = " ".join(m.text for m in moves)
            self.out.unresolved.append(Unresolved([m.ref for m in moves], text, reason))


def _square(index: int) -> chess.Square:
    """Square of a diagram index (0 = a8 … 63 = h1)."""
    return chess.square(index % 8, 7 - index // 8)


def _printed_mate(text: str) -> bool:
    return text.rstrip("!? .").endswith(("#", "‡", "\ue001"))


def _mates_hold(trial: _Trial, moves: list[FragMove]) -> bool:
    """Every move of the trial printed as mate ("Qh7#") is mate on the board."""
    board = trial.parent.board()
    for fm, move in zip(moves, trial.moves):
        board.push(move)
        if _printed_mate(fm.text) and not board.is_checkmate():
            return False
    return True


def _number_fits(number: tuple[int, bool | None], board: chess.Board, lenient: bool) -> bool:
    n, black = number
    if black is not None and black != (board.turn == chess.BLACK):
        return False
    # OCR misreads numbers ("6" for "8"); inside a fragment the moves themselves are the better evidence.
    return lenient or n == board.fullmove_number


def _next_numbered(moves: list[FragMove], start: int) -> int:
    return next((i for i in range(start, len(moves)) if moves[i].number is not None), len(moves))
