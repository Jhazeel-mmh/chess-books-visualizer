"""Working out badly scanned moves: the legal moves that best fit what is printed, decided by what follows."""

import chess

from cbv.ingest.model import Block, DocStream
from cbv.notation.pieces import letter_map
from cbv.parse import decoder
from cbv.parse.anchoring import _number_fits, anchor
from cbv.parse.fragments import Fragment, events


def fragment(text: str) -> list:
    return [e for e in events(DocStream([Block("para", text, ocr=True)])) if isinstance(e, Fragment)][0].moves


def played(board: chess.Board, moves: list[chess.Move]) -> list[str]:
    out = []
    for m in moves:
        out.append(board.san(m))
        board.push(m)
    return out


def board_after(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


# Nimzowitsch – von Freymann, Vilnius 1912, as far as 7.Bd3.
GAME = ["e4", "e6", "d4", "d5", "e5", "c5", "Nf3", "cxd4", "Nxd4", "Nc6", "Nxc6", "bxc6", "Bd3"]


def test_an_unknown_spelling_on_a_misread_square_is_worked_out_from_the_moves_after_it():
    # The scan prints 7...Qc7 as "'eNe7": a spelling never seen, and c read as e.
    board = board_after(*GAME)
    found = decoder.decode(letter_map("en"), board.copy(), fragment("7 ... 'eNe7 8.Bf4 g5 9.Bg3 Bg7 10.Qe2 Ne7"), _number_fits)
    assert played(board.copy(), found.moves) == ["Qc7", "Bf4", "g5", "Bg3", "Bg7", "Qe2", "Ne7"]
    assert 0 in found.guessed and 1 not in found.guessed


def test_a_pawn_printed_like_the_books_rook():
    # A book whose rooks come out as "g": "27.gxh5 gxh5" are still pawn captures.
    board = chess.Board("6k1/5p2/6p1/7p/6P1/7P/5P2/6K1 w - - 0 27")
    pieces = letter_map("en", {"g": chess.ROOK})
    found = decoder.decode(pieces, board.copy(), fragment("27.gxh5 gxh5"), _number_fits)
    assert played(board.copy(), found.moves) == ["gxh5", "gxh5"]


def test_a_printed_check_decides_between_moves_that_fit_as_well():
    # "?d7+" with an unknown piece: the rook may go to d7 too, but only the queen gives check there.
    board = chess.Board("4k3/1R6/8/8/8/8/8/3Q2K1 w - - 0 1")
    found = decoder.decode(letter_map("en"), board.copy(), fragment("1.%d7+ Kf8 2.Qd8#"), _number_fits)
    assert played(board.copy(), found.moves) == ["Qd7+", "Kf8", "Qd8#"]


def test_a_damaged_move_with_nothing_after_it_is_left_alone():
    board = chess.Board("4k3/1R6/8/8/8/8/8/3Q2K1 w - - 0 1")
    assert decoder.decode(letter_map("en"), board.copy(), fragment("1.%d7+ Kf8"), _number_fits).moves == []


def test_nothing_is_taken_when_two_readings_fit_as_well():
    board = chess.Board()
    found = decoder.decode(letter_map("en"), board.copy(), fragment("1.%f3"), _number_fits)
    assert found.moves == []  # Nf3 or f3: nothing after it decides


def test_a_game_starts_from_a_garbled_first_move():
    evs = events(DocStream([Block("para", "1.tLlf3 d5 2.g3 c5 3.Bg2 Nc6 4.O-O e5", ocr=True)]))
    a = anchor(evs, letter_map("en"), "paragraph", repair=True)
    assert [n.san for n in a.games[0].mainline()[1:]] == ["Nf3", "d5", "g3", "c5", "Bg2", "Nc6", "O-O", "e5"]
    assert a.games[0].mainline()[1].guessed  # shown as uncertain


def test_a_main_line_broken_off_is_read_with_the_next_fragment():
    # 7...Qc7 printed as "'eNe7" can't be told from Qe7 by "8.Bf4 g5" alone; the next paragraph decides.
    blocks = [
        Block("para", "1.e4 e6 2.d4 d5 3.e5 c5 4.Nf3 cxd4 5.Nxd4 Nc6 6.Nxc6 bxc6 7.Bd3 'eNe7 8.Bf4 g5", ocr=True),
        Block("para", "Esto no es muy sólido.", ocr=True),
        Block("para", "9.Bg3 Bg7 10.Qe2 Ne7 11.O-O h5", ocr=True),
    ]
    a = anchor(events(DocStream(blocks)), letter_map("en"), "paragraph", repair=True)
    line = [n.san for n in a.games[0].mainline()[1:]]
    assert line[12:20] == ["Bd3", "Qc7", "Bf4", "g5", "Bg3", "Bg7", "Qe2", "Ne7"]
    qc7 = a.games[0].mainline()[14]
    assert qc7.guessed  # shown as uncertain
    assert not any("'eNe7" in u.text for u in a.unresolved)
