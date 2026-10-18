"""Matches a printed move against the legal moves of a position.

This is what makes the parser notation-agnostic: a printed move is accepted only
if exactly one legal move fits every detail the book gave (piece, origin hints,
capture mark, destination, promotion piece).
"""

from __future__ import annotations

import re
from dataclasses import replace

import chess

from .pieces import PieceMap
from .tokenizer import ParsedMove


def candidates(board: chess.Board, pm: ParsedMove, pieces: PieceMap) -> list[chess.Move]:
    if pm.fixed:
        return fixed_candidates(board, pm)
    if pm.unknown is not None:
        return unreadable_candidates(board, pm.unknown, pieces)
    if pm.castle:
        return [
            m for m in board.generate_castling_moves()
            if (board.is_kingside_castling(m) if pm.castle == "K" else board.is_queenside_castling(m))
        ]

    piece_type = pieces.piece(pm.piece) if pm.piece else chess.PAWN
    if piece_type is None and len(pm.piece) > 1 and pm.piece[-1] in "abcdefgh" and pm.from_file is None:
        # OCR glued the origin file to the piece ("ttlbd2": "ttl" is a knight, from the b-file).
        base = pieces.piece(pm.piece[:-1])
        if base is not None:
            pm = replace(pm, piece=pm.piece[:-1], from_file="abcdefgh".index(pm.piece[-1]))
            piece_type = base
    if piece_type is None and (pm.weak or pm.piece not in pieces.wildcards):
        return []
    promotion = None
    if pm.promotion:
        promotion = pieces.piece(pm.promotion)
        if promotion in (None, chess.PAWN, chess.KING):
            return []

    # Only generate moves of the right piece type, from the printed origin hints, to the printed square.
    if piece_type is None:
        from_mask = board.occupied_co[board.turn] & ~board.pawns
    else:
        from_mask = board.pieces_mask(piece_type, board.turn)
    if pm.from_file is not None:
        from_mask &= chess.BB_FILES[pm.from_file]
    if pm.from_rank is not None:
        from_mask &= chess.BB_RANKS[pm.from_rank]
    found = []
    for m in board.generate_legal_moves(from_mask, chess.BB_SQUARES[pm.to_square]):
        if pm.capture and not board.is_capture(m):
            continue
        # Books often leave out "=Q"; an unmarked promotion means a queen.
        if m.promotion != (promotion or (chess.QUEEN if m.promotion else None)):
            continue
        found.append(m)
    hint = pieces.hints.get(pm.piece) if piece_type is None and len(found) > 1 else None
    if hint is not None:
        found = [m for m in found if board.piece_type_at(m.from_square) == hint]
    return found


def match(board: chess.Board, pm: ParsedMove, pieces: PieceMap) -> chess.Move | None:
    found = candidates(board, pm, pieces)
    return found[0] if len(found) == 1 else None


# Square characters that OCR mixes up: c/e and b/h in files; 3/8, 5/6, 6/8 and 1/7 in ranks.
_FILE_LOOKALIKES = {1: (7,), 7: (1,), 2: (4,), 4: (2,)}
_RANK_LOOKALIKES = {0: (6,), 6: (0,), 2: (7,), 7: (2, 5), 4: (5,), 5: (4, 7)}


def lookalikes(pm: ParsedMove) -> list[ParsedMove]:
    """The printed move with one OCR confusion undone ("Ne3" may have been "Nc3")."""
    if pm.castle or pm.to_square is None:
        return []
    file, rank = chess.square_file(pm.to_square), chess.square_rank(pm.to_square)
    out = [replace(pm, to_square=chess.square(f, rank)) for f in _FILE_LOOKALIKES.get(file, ())]
    out += [replace(pm, to_square=chess.square(file, r)) for r in _RANK_LOOKALIKES.get(rank, ())]
    if pm.from_file is not None:
        out += [replace(pm, from_file=f) for f in _FILE_LOOKALIKES.get(pm.from_file, ())]
    return out


_SQUARE = re.compile(r"[a-h][1-8]")


def unreadable_candidates(board: chess.Board, word: str, pieces: PieceMap) -> list[chess.Move]:
    """The legal moves an unreadable OCR word may stand for, narrowed by what can still be read.

    "ltlc6" may have lost its shape but still shows a square; "ttJx" starts with a spelling
    the book uses for a knight. A hint that rules out every legal move is ignored.
    """
    found = list(board.legal_moves)
    squares = _SQUARE.findall(word)
    if squares:
        to = chess.parse_square(squares[-1])
        found = [m for m in found if m.to_square == to] or found
    key = max((k for k in pieces.symbols if len(k) >= 2 and word.startswith(k)), key=len, default=None)
    if key is not None:
        piece_type = pieces.symbols[key]
        found = [m for m in found if board.piece_type_at(m.from_square) == piece_type] or found
    return found


def fixed_candidates(board: chess.Board, pm: ParsedMove) -> list[chess.Move]:
    """A move the reader entered: that move, but only in the position it was entered for."""
    placement, side = (pm.before or "").split()[:2] if pm.before else ("", "")
    if board.board_fen() != placement or board.turn != (side == "w"):
        return []
    move = chess.Move.from_uci(pm.fixed)
    return [move] if board.is_legal(move) else []
