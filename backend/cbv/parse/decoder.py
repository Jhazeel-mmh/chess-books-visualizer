"""Working out the moves of a badly scanned fragment: the legal moves that best fit what is printed.

When a fragment of an OCR'd book breaks (a move that isn't legal as read, a piece spelling never
seen, a square misread), every legal move is scored against the printed token: the square (with
the look-alikes OCR confuses), the piece the spelling stands for, the capture sign, the file it
comes from, castling, and the check or mate printed after it. A beam search keeps the best few
sequences through the fragment, so the moves after a doubtful one decide it. A reading is taken
only when it is good on average and clearly better than the next one; the moves it had to work
out are marked as guessed, so the reader shows them as uncertain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import chess

from ..notation.matcher import _FILE_LOOKALIKES, _RANK_LOOKALIKES, glued_origin
from ..notation.pieces import PieceMap
from .fragments import FragMove

# How many sequences the search keeps after each move.
BEAM = 12
# A move scoring less than this is not considered at all.
MIN_MOVE = 0.5
# Taken only if the moves score at least this on average, none below WEAK_MOVE…
GOOD_AVERAGE = 2.5
WEAK_MOVE = 1.0
# …and the best sequence beats the next one by this much.
MARGIN = 1.5
# A move scoring this much was read as printed; below it, it was worked out (shown as uncertain).
AS_PRINTED = 4.5
# The score a first move needs for a game to start from it ("1.e4e6" read as 1.e4).
GAME_START = 3.5
# Check each worked-out move against the best reading without it.
VERIFY = False
# Moves after a worked-out one that must be read as printed: after a damaged print, and after a
# clean-looking one (which must also score this much: a look-alike square, say).
CONFIRM_DOUBTFUL = 2
CONFIRM_CLEAN = 3
CLEAN_MISREAD = 3.5
# A damaged print with nothing after it is taken only if it fits this well.
ALONE = 4.0

_SQUARE = re.compile(r"([a-h])\s?([1-8SsIilZzBG])")
_RANKS = str.maketrans("SsIilZzBG", "551112286")


@dataclass
class Decoded:
    moves: list[chess.Move]
    # Indexes of the moves worked out rather than read as printed.
    guessed: set[int]


def printed_square(fm: FragMove) -> chess.Square | None:
    if fm.move.to_square is not None:
        return fm.move.to_square
    found = _SQUARE.findall(fm.text)
    return chess.parse_square(found[-1][0] + found[-1][1].translate(_RANKS)) if found else None


def _looks_like(printed: chess.Square, real: chess.Square) -> bool:
    f, r = chess.square_file(printed), chess.square_rank(printed)
    rf, rr = chess.square_file(real), chess.square_rank(real)
    return (r == rr and rf in _FILE_LOOKALIKES.get(f, ())) or (f == rf and rr in _RANK_LOOKALIKES.get(r, ()))


def score(pieces: PieceMap, board: chess.Board, fm: FragMove, move: chess.Move) -> float:
    """How well a legal move fits the printed token (about 5.5 for a perfect fit)."""
    split = glued_origin(fm.move) if fm.move.piece is not None else None
    whole = _score(pieces, board, fm, fm.move, move)
    if split is None:
        return whole
    # "13bc8": a spelling with the rook's file glued to it, or a spelling that happens to end in "b".
    return max(whole, _score(pieces, board, fm, split, move))


def _score(pieces: PieceMap, board: chess.Board, fm: FragMove, pm, move: chess.Move) -> float:
    if pm.castle or board.is_castling(move):
        long = chess.square_file(move.to_square) == 2
        return 5.0 if pm.castle and board.is_castling(move) and (pm.castle == "Q") == long else -9.0
    piece = board.piece_type_at(move.from_square)
    s = 0.0
    to = printed_square(fm)
    if to is not None:
        if to == move.to_square:
            s += 3
        elif _looks_like(to, move.to_square):
            s += 2
        elif chess.square_file(to) == chess.square_file(move.to_square) or chess.square_rank(to) == chess.square_rank(move.to_square):
            s += 0.3
        else:
            s -= 1
    symbol = pm.piece
    if pm.unknown is not None:
        # An unreadable word may still start with the book's spelling of a piece ("lLln": a knight).
        symbol = max((k for k in pieces.symbols if len(k) >= 2 and pm.unknown.startswith(k)), key=len, default=None)
        if symbol is not None:
            s += 1.5 if pieces.symbols[symbol] == piece else -1.5
    elif symbol is None:
        s += 1.5 if piece == chess.PAWN else -1.5
    else:
        meant = pieces.symbols.get(symbol) or pieces.hints.get(symbol)
        if pm.seen is not None:
            # The figurine's shape: it settles an unknown spelling; against a known one, only when sure.
            meant = pm.seen if meant is None or pm.seen_sure else (meant if meant == pm.seen else None)
        if len(symbol) == 1 and symbol in "abcdefgh" and piece == chess.PAWN and chess.square_file(move.from_square) == "abcdefgh".index(symbol):
            s += 1.5  # a book's rook printed as "g" may also be the g-pawn ("27.gxh5")
        elif meant is None:
            s += 0.3 if piece != chess.PAWN else -0.5
        elif meant == piece:
            s += 1.5
        else:
            s -= 1.5
    # OCR seldom invents an "x", but may drop one; a pawn capture also shows its file ("dxe5"), so a
    # bare "e5" taking something would have lost two characters.
    capture = board.is_capture(move)
    s += 0.5 if pm.capture == capture else (-2.0 if pm.capture else -0.5)
    if capture and piece == chess.PAWN and symbol is None and pm.from_file is None and not pm.capture:
        s -= 1.5
    if pm.from_file is not None:
        f = chess.square_file(move.from_square)
        s += 0.5 if f == pm.from_file else (0.2 if f in _FILE_LOOKALIKES.get(pm.from_file, ()) else -0.5)
    if pm.from_rank is not None:
        s += 0.5 if chess.square_rank(move.from_square) == pm.from_rank else -0.5
    printed_check = "+" in fm.text or "#" in fm.text
    if printed_check and not board.gives_check(move):
        s -= 2.5
    return s


def decode(pieces: PieceMap, board: chess.Board, moves: list[FragMove], number_fits, strict: set[int] = frozenset({0})) -> Decoded:
    """The best-fitting legal moves for the fragment's printed moves, as far as they are clear.

    ``number_fits(number, board, lenient)`` says whether a printed move number fits a position; it
    is checked strictly for the moves in ``strict`` (the first of each fragment), loosely elsewhere.
    """
    def search(forbid: dict[int, chess.Move] | None = None, length: int | None = None) -> list[list[tuple]]:
        return _search(pieces, board, moves[:length], number_fits, strict, forbid)

    best_at = search()
    # The longest start of the fragment that is well read and clearly the best reading.
    for n in range(len(best_at), 0, -1):
        total, _, played, scores = best_at[n - 1][0]
        if total / n < GOOD_AVERAGE or min(scores) < WEAK_MOVE:
            continue
        guessed = {i for i, sc in enumerate(scores) if sc < AS_PRINTED}
        # A worked-out move needs the moves after it, read as printed, to bear it out: more of them
        # when the print looked clean (a known spelling on a clear square is seldom misread). If one
        # isn't, a shorter reading (perhaps a different one) may still be.
        if any(not _borne_out(pieces, moves, scores, i, n) for i in guessed):
            continue
        # A reading kept beside it that disagrees on a worked-out move, and fits nearly as well, makes
        # it a guess between two: none is taken. (One reading a clearly printed move differently is
        # just a worse reading of the same text.)
        rivals = [st[0] for st in best_at[n - 1][1:] if any(st[2][i] != played[i] for i in guessed)]
        if rivals and total - max(rivals) < MARGIN:
            continue
        # Each worked-out move must win clearly: read without it, the fragment must score MARGIN less.
        # If it doesn't, only the moves both readings agree on are taken ("6.Txe6 bxe6" may be Nxe6
        # fxe6 or Nxc6 bxc6: nothing before the knight's move is in doubt).
        keep = n
        for i in sorted(guessed) if VERIFY else ():
            if i >= keep:
                break
            rival = search({i: played[i]}, n)
            if len(rival) < n:
                continue  # without that move the fragment can't be read this far
            r_total, _, r_played, _ = rival[n - 1][0]
            if total - r_total < MARGIN:
                keep = min(keep, next(j for j in range(n) if r_played[j] != played[j]))
        if keep < n and (keep == 0 or sum(scores[:keep]) / keep < GOOD_AVERAGE):
            return Decoded([], set())
        return Decoded(played[:keep], {i for i in guessed if i < keep})
    return Decoded([], set())


def doubtful(pieces: PieceMap, fm: FragMove) -> bool:
    """Whether the printed move looks damaged: an unreadable word, a piece spelling never learned,
    or a figurine whose shape says another piece than its spelling."""
    pm = fm.move
    if pm.unknown is not None:
        return True
    if pm.piece is None:
        return False
    meant = pieces.symbols.get(pm.piece) or pieces.hints.get(pm.piece)
    return meant is None or (pm.seen is not None and pm.seen != meant)


def _borne_out(pieces: PieceMap, moves: list[FragMove], scores: list[float], i: int, n: int) -> bool:
    clean = not doubtful(pieces, moves[i])
    # A clean first move that doesn't fit says the fragment belongs elsewhere, not that it was misread.
    if clean and (i == 0 or scores[i] < CLEAN_MISREAD):
        return False
    need = CONFIRM_CLEAN if clean else CONFIRM_DOUBTFUL
    after = scores[i + 1:i + 1 + need]
    if len(after) < need:
        # Nothing after it to tell: only a move that fits its print very well, and only if damaged.
        return doubtful(pieces, moves[i]) and scores[i] >= ALONE and all(sc >= AS_PRINTED for sc in after)
    return all(sc >= AS_PRINTED for sc in after) and i + need < n + 1


def _search(pieces: PieceMap, board: chess.Board, moves: list[FragMove], number_fits, strict: set[int],
            forbid: dict[int, chess.Move] | None) -> list[list[tuple]]:
    """The beam (best sequences, total score first) after each printed move; ``forbid`` keeps a
    move from being played at its index."""
    beam: list[tuple[float, chess.Board, list[chess.Move], list[float]]] = [(0.0, board, [], [])]
    best_at: list[list[tuple]] = []
    for i, fm in enumerate(moves):
        nxt = []
        banned = forbid.get(i) if forbid else None
        for total, b, played, scores in beam:
            if fm.number is not None and not number_fits(fm.number, b, i not in strict):
                continue
            for move in b.legal_moves:
                if move == banned:
                    continue
                sc = score(pieces, b, fm, move)
                if sc < MIN_MOVE:
                    continue
                after = b.copy(stack=False)
                after.push(move)
                nxt.append((total + sc, after, played + [move], scores + [sc]))
        if not nxt:
            break
        nxt.sort(key=lambda x: -x[0])
        seen: set[str] = set()
        beam = []
        for state in nxt:
            key = state[1].fen()
            if key not in seen:
                seen.add(key)
                beam.append(state)
            if len(beam) == BEAM:
                break
        best_at.append(beam)
    return best_at


def plausible_start(pieces: PieceMap, fm: FragMove) -> bool:
    """Whether a fragment numbered 1 can start a game: some first move fits it well."""
    board = chess.Board()
    return max(score(pieces, board, fm, m) for m in board.legal_moves) >= GAME_START
