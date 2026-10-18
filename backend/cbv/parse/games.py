"""Game trees built from a book's move fragments, and their PGN export."""

from __future__ import annotations

from dataclasses import dataclass, field

import chess
import chess.pgn

from ..ingest.model import TextRef

# Positions are indexed by (fullmove number, side to move) so that a fragment
# printed as "12...Nc6" finds every position where it is Black's 12th move.
PositionKey = tuple[int, chess.Color]


def position_key(fen: str) -> PositionKey:
    fields = fen.split()
    return int(fields[5]), fields[1] == "w"


@dataclass(eq=False)
class Node:
    id: str
    parent: Node | None
    move: chess.Move | None
    san: str | None
    fen: str
    order: int
    children: list[Node] = field(default_factory=list)
    nags: set[int] = field(default_factory=set)
    # How often a main-line-styled fragment (bold, or starting a paragraph) printed this move.
    votes: int = 0
    refs: list[TextRef] = field(default_factory=list)
    # The refs where the move was worked out from damaged OCR text rather than read.
    guessed: set[TextRef] = field(default_factory=set)
    # The refs where the reader entered the move (move fixes).
    fixed: set[TextRef] = field(default_factory=set)
    _board: chess.Board | None = field(default=None, repr=False)

    def board(self) -> chess.Board:
        """A fresh copy of the position after this move (parsing FENs is slow, copying is not)."""
        if self._board is None:
            self._board = chess.Board(self.fen)
        return self._board.copy(stack=False)

    def ordered_children(self) -> list[Node]:
        """Children with the main continuation first: voted moves, then creation order."""
        return sorted(self.children, key=lambda c: (c.votes == 0, c.order))

    def path(self) -> list[Node]:
        node, out = self, []
        while node is not None:
            out.append(node)
            node = node.parent
        return out[::-1]


class Game:
    def __init__(self, game_id: str, title: str | None, start_fen: str, ids: _Ids):
        self.id = game_id
        self.title = title
        self.start_fen = start_fen
        self._ids = ids
        self.root = Node(f"{game_id}r", None, None, None, start_fen, ids.next_order())
        self.index: dict[PositionKey, list[Node]] = {position_key(start_fen): [self.root]}

    def add_child(self, parent: Node, move: chess.Move) -> Node:
        board = parent.board()
        san = board.san(move)
        board.push(move)
        child = Node(self._ids.next_node(), parent, move, san, board.fen(), self._ids.next_order(), _board=board)
        parent.children.append(child)
        self.index.setdefault(position_key(child.fen), []).append(child)
        return child

    def mainline(self) -> list[Node]:
        node, out = self.root, [self.root]
        while node.children:
            node = node.ordered_children()[0]
            out.append(node)
        return out

    def nodes(self) -> list[Node]:
        """All nodes, depth first, main continuation before variations."""
        out, stack = [], [self.root]
        while stack:
            node = stack.pop()
            out.append(node)
            stack.extend(reversed(node.ordered_children()))
        return out

    def to_dict(self) -> dict:
        main = {n.id for n in self.mainline()}
        return {
            "id": self.id,
            "title": self.title,
            "start_fen": self.start_fen,
            "root": self.root.id,
            "nodes": [
                {
                    "id": n.id,
                    "parent": n.parent.id if n.parent else None,
                    "children": [c.id for c in n.ordered_children()],
                    "san": n.san,
                    "uci": n.move.uci() if n.move else None,
                    "fen": n.fen,
                    "nags": sorted(n.nags),
                    "mainline": n.id in main,
                    "refs": [[r.block, r.start, r.end] for r in n.refs],
                    "uncertain": bool(n.refs) and all(r in n.guessed for r in n.refs),
                }
                for n in self.nodes()
            ],
        }

    def to_pgn(self) -> str:
        game = chess.pgn.Game()
        game.headers["Event"] = self.title or "?"
        if self.start_fen != chess.STARTING_FEN:
            game.setup(chess.Board(self.start_fen))
        stack = [(game, self.root)]
        while stack:
            pgn_node, node = stack.pop()
            for child in node.ordered_children():
                stack.append((pgn_node.add_variation(child.move, nags=child.nags), child))
        return str(game)


class _Ids:
    def __init__(self):
        self._node = 0
        self._order = 0

    def next_node(self) -> str:
        self._node += 1
        return f"n{self._node}"

    def next_order(self) -> int:
        self._order += 1
        return self._order
