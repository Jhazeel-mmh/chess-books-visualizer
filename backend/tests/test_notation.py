import chess
import pytest

from cbv.notation.matcher import match
from cbv.notation.pieces import letter_map
from cbv.notation.tokenizer import tokenize

EN, ES = letter_map("en"), letter_map("es")


def moves(text):
    return [t.move for t in tokenize(text) if t.kind == "move"]


def kinds(text):
    return [(t.kind, t.text) for t in tokenize(text)]


@pytest.mark.parametrize("text, number, black", [
    ("12.Nf3", 12, False),
    ("12. Nf3", 12, False),
    ("12 Nf3", 12, False),
    ("12...Nc6", 12, True),
    ("12…Nc6", 12, True),
    ("12. ...Nc6", 12, True),
    ("12 ... Nc6", 12, True),
])
def test_move_numbers(text, number, black):
    first = tokenize(text)[0]
    assert (first.kind, first.number, first.black) == ("number", number, black)


def test_suffix_and_standalone_nags():
    nags = [t.nag for t in tokenize("13.Bxf7+!? Kxf7 ± 14.Qh5 ?? +-") if t.kind == "nag"]
    assert nags == [5, 16, 4, 18]


def test_results_are_not_castling():
    assert kinds("0-0 0-1 O-O-O 1/2-1/2") == [
        ("move", "0-0"), ("result", "0-1"), ("move", "O-O-O"), ("result", "1/2-1/2"),
    ]


def test_moves_inside_words_are_ignored():
    assert moves("Kasparov played well; Bb5x is not a move") == []


def test_en_dash_castling_and_long_algebraic():
    board = chess.Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert match(board, moves("0–0–0")[0], EN) == chess.Move.from_uci("e1c1")
    assert match(chess.Board(), moves("Ng1-f3")[0], EN) == chess.Move.from_uci("g1f3")
    assert match(chess.Board(), moves("e2-e4")[0], EN) == chess.Move.from_uci("e2e4")


@pytest.mark.parametrize("text, pieces, uci", [
    ("Nf3", EN, "g1f3"),
    ("Cf3", ES, "g1f3"),
    ("♘f3", EN, "g1f3"),
    ("♞f3", ES, "g1f3"),  # figurines are colourless in books
])
def test_piece_letters_and_figurines(text, pieces, uci):
    assert match(chess.Board(), moves(text)[0], pieces) == chess.Move.from_uci(uci)


def test_r_means_rook_in_english_and_king_in_spanish():
    board = chess.Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
    pm = moves("Rd1")[0]
    assert match(board, pm, EN) == chess.Move.from_uci("a1d1")
    assert match(board, pm, ES) == chess.Move.from_uci("e1d1")


def test_disambiguation_capture_and_promotion():
    board = chess.Board("1n2k3/P7/8/8/8/2N1N3/8/4K3 w - - 0 1")
    assert match(board, moves("Ncd5")[0], EN) == chess.Move.from_uci("c3d5")
    assert match(board, moves("Nd5")[0], EN) is None  # ambiguous as printed
    assert match(board, moves("axb8=N")[0], EN) == chess.Move.from_uci("a7b8n")
    assert match(board, moves("axb8")[0], EN) == chess.Move.from_uci("a7b8q")
    assert match(board, moves("axb8C")[0], ES) == chess.Move.from_uci("a7b8n")
    assert match(board, moves("Nxd5")[0], EN) is None  # capture mark, but nothing to take


def test_glyph_after_a_move_off_the_last_rank_is_not_a_promotion():
    board = chess.Board("3q1rk1/5pbp/5Qp1/8/8/2B5/5PPP/6K1 w - - 0 1")
    assert match(board, moves("1.♕xg7\ue001")[0], EN) == chess.Move.from_uci("f6g7")
