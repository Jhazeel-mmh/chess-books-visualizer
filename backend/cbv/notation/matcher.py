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

    split = glued_origin(pm) if pm.piece else None
    if split is not None and pieces.piece(split.piece) is not None:
        # OCR may have glued the origin to the piece ("ttlbd2": "ttl" is a knight, from the b-file;
        # "tLl1d2"), even where the whole spelling was learned as well. Read that way if it fits;
        # otherwise the last character was part of the spelling.
        found = _matching(board, split, pieces.piece(split.piece), pieces)
        if found or pieces.piece(pm.piece) is None:
            return found
    return _matching(board, pm, pieces.piece(pm.piece) if pm.piece else chess.PAWN, pieces)


def _matching(board: chess.Board, pm: ParsedMove, piece_type: chess.PieceType | None, pieces: PieceMap) -> list[chess.Move]:
    """The legal moves of ``piece_type`` (None: any piece) that fit every printed detail."""
    if pm.seen is not None and pm.piece and (piece_type is None or (pm.seen_sure and piece_type != pm.seen)):
        # A scan: the figurine's shape, where the spelling is unknown or clearly says another piece.
        piece_type = pm.seen
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
    # A pawn printed with neither its file nor "x" ("e5") goes straight ahead: captures say "dxe5".
    pawn_push = piece_type == chess.PAWN and pm.from_file is None and not pm.capture
    found = []
    for m in board.generate_legal_moves(from_mask, chess.BB_SQUARES[pm.to_square]):
        if pm.capture and not board.is_capture(m):
            continue
        if pawn_push and board.is_capture(m):
            continue
        # Books often leave out "=Q"; an unmarked promotion means a queen.
        if m.promotion != (promotion or (chess.QUEEN if m.promotion else None)):
            continue
        found.append(m)
    hint = pieces.hints.get(pm.piece) if piece_type is None and len(found) > 1 else None
    if hint is not None:
        found = [m for m in found if board.piece_type_at(m.from_square) == hint]
    return found


def glued_origin(pm: ParsedMove) -> ParsedMove | None:
    """The move with a file or rank split off the end of its piece spelling ("13bc8" → "13", b-file)."""
    symbol = pm.piece
    if not symbol or len(symbol) < 2 or pm.from_file is not None or pm.from_rank is not None:
        return None
    last = symbol[-1]
    if last in "abcdefgh":
        return replace(pm, piece=symbol[:-1], from_file="abcdefgh".index(last))
    if last in "12345678":
        return replace(pm, piece=symbol[:-1], from_rank=int(last) - 1)
    return None


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
