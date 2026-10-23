"""Scanned books: moves read from OCR text, where figurines come out as junk."""

from array import array

import chess

from cbv.ingest.model import Block, DocStream
from cbv.ingest.pdf import _diagram_labels, _Line, _running_lines
from cbv.notation.matcher import candidates, lookalikes
from cbv.notation.pieces import PieceMap, letter_map
from cbv.notation.tokenizer import ParsedMove, tokenize
from cbv.parse import _guess_symbols, analyze
from cbv.parse.anchoring import anchor
from cbv.parse.fragments import _ref, events
from tests.helpers import diagram, header


def ocr(text: str) -> Block:
    return Block("para", text, ocr=True)


def ocr_moves(text: str) -> list[tuple]:
    return [(t.text, t.move.piece, chess.square_name(t.move.to_square), t.move.weak)
            for t in tokenize(text, ocr=True) if t.kind == "move" and not t.move.castle]


def test_junk_before_a_square_is_the_piece():
    assert ocr_moves("1 l:.xf8+! 1-0 l ...'it>xf8 2 'ii'h8#") == [
        ("l:.xf8+!", "l:", "f8", False), ("'it>xf8", "it>", "f8", False), ("'ii'h8#", "ii", "h8", False),
    ]


def test_ranks_read_as_letters():
    # "eS" is e5 and "!hl" a rook to h1; "las" might be a rook to a5 in a book that prints rooks as "l",
    # so it is weak; "es" alone is just a word.
    assert ocr_moves("1.eS 2.!hl las es") == [("eS", None, "e5", False), ("!hl", "!", "h1", False), ("las", "l", "a5", True)]


def test_move_numbers_with_look_alike_digits_and_unclear_sides():
    numbers = [(t.number, t.black) for t in tokenize("l ...Dh8 IO.e4 2 . .. .if8 21..Wf5 lS.Kg2", ocr=True)
               if t.kind == "number"]
    assert numbers == [(1, True), (10, False), (2, True), (21, None), (15, False)]


def test_evaluation_glued_to_a_move_is_not_a_check():
    tokens = tokenize("6.ih6+- 7.Kg2", ocr=True)
    assert [(t.kind, t.text) for t in tokens[:3]] == [("number", "6."), ("move", "ih6"), ("nag", "+-")]


def test_control_characters_are_figurines_not_spaces():
    assert ocr_moves("1 \x1df6+!")[0][1] == "␝"


def test_look_alike_squares():
    nc3 = {chess.square_name(m.to_square) for m in lookalikes(ParsedMove(piece="N", to_square=chess.E3))}
    assert nc3 == {"c3", "e8"}


def test_piece_spellings_are_learned_from_unambiguous_moves():
    # Ten puzzles where only one piece can reach the square: each spelling gets two votes.
    puzzles = [
        ("6k1/5ppp/8/8/8/8/5PPP/3R2K1", "1 l:td8#"), ("7k/6pp/8/8/8/8/8/R5K1", "1 l:ta8#"),
        ("6rk/6pp/7N/8/8/8/8/6K1", "1 lLlf7#"), ("k7/8/8/8/8/8/8/1N4K1", "1 lLlc3"),
        ("k7/8/8/8/8/8/8/5BK1", "1 .i.c4"), ("k7/8/8/8/8/8/1B6/6K1", "1 .i.e5"),
        ("k7/8/8/8/8/8/8/3Q2K1", "1 'iVd5"), ("k7/8/8/8/8/8/8/1Q4K1", "1 'iVb5"),
        ("k7/8/8/8/8/8/8/6K1", "1 'it>f2"), ("k7/8/8/8/8/8/8/6K1", "1 'it>h2"),
    ]
    blocks = [b for placement, solution in puzzles for b in (diagram(placement), ocr(solution))]
    # Then a game where "any piece" would be ambiguous: Qf3 or Nf3, Nf6 or Qf6, Ke2, Qe2 or Be2.
    blocks += [header("Smith – Jones"), ocr("1.e4 e5 2.'iVf3 lLlf6 3.'it>e2")]
    a = analyze(DocStream(blocks))
    learned = {s: p for s, p in a.pieces.symbols.items() if len(s) > 1 or s == "i"}
    assert learned == {"l:t": chess.ROOK, "lLl": chess.KNIGHT, "i": chess.BISHOP, "iV": chess.QUEEN, "it>": chess.KING}
    assert len(a.anchored.diagram_nodes) == 10
    game = a.anchored.games[-1]
    assert [n.san for n in game.mainline()[1:]] == ["e4", "e5", "Qf3", "Nf6", "Ke2"]
    assert a.to_dict()["notation"]["ocr"]["learned"] == {"l:t": "R", "lLl": "N", "i": "B", "iV": "Q", "it>": "K"}


def test_unknown_spelling_is_guessed_from_similar_ones():
    learned = {"tLl": chess.KNIGHT, "lLl": chess.KNIGHT, "LLl": chess.KNIGHT, "l:t": chess.ROOK, ".l:t": chess.ROOK}
    assert _guess_symbols(learned, {"Ll"}) == {"Ll": chess.KNIGHT}
    # A guess only decides between legal moves: "Ll" to f3 could be the knight or the queen.
    board = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2")
    guessed = PieceMap("en", letter_map("en").symbols, True, frozenset({"Ll"}), {"Ll": chess.KNIGHT})
    assert candidates(board, ParsedMove(piece="Ll", to_square=chess.F3), guessed) == [chess.Move.from_uci("g1f3")]


def test_look_alike_characters_are_repaired_when_the_game_then_makes_sense():
    # "2.e4" is legal but wrong: the game only goes on if it was "2.c4" and "4.Ne3" was "4.Nc3".
    text = "1.d4 Nf6 2.e4 e6 3.Nf3 b6 4.Ne3 Bb7 5.Bg5 h6 6.Bh4 Be7 7.e3 d6 8.Bd3"
    evs = events(DocStream([ocr(text)]))
    plain = anchor(evs, letter_map("en"), "paragraph")
    assert [n.san for n in plain.games[0].mainline()[1:]] == ["d4", "Nf6", "e4", "e6", "Nf3", "b6"]
    fixed = anchor(evs, letter_map("en"), "paragraph", repair=True)
    assert " ".join(n.san for n in fixed.games[0].mainline()[1:]) == "d4 Nf6 c4 e6 Nf3 b6 Nc3 Bb7 Bg5 h6 Bh4 Be7 e3 d6 Bd3"


def test_a_failed_solution_is_not_continued_from_the_diagram():
    # "1 Bd5+" can't be read; "2 Kh2" belongs to that solution and must not start at the diagram.
    a = analyze(DocStream([diagram("6k1/8/8/8/8/8/8/6K1"), ocr("1 Xb5+ 'it>g7 2 'it>h2")]))
    assert a.anchored.games == []


def test_references_from_ocr_and_decimal_exercise_numbers():
    assert _ref("415} White to play", {"415"}, ocr=True) == "415"
    assert _ref("2.01 \nSí, 1.Cc4!", {"2.01"}) == "2.01"
    assert _ref("2.0 Juegan", {"2.0"}) is None


def _line(text: str, x0: float, y0: float, x1: float, y1: float) -> _Line:
    width = (x1 - x0) / max(len(text), 1)
    boxes = array("f")
    for i in range(len(text)):
        boxes.extend((x0 + i * width, y0, x0 + (i + 1) * width, y1))
    return _Line(0, text, boxes, [], 9.0, (x0, y0, x1, y1))


def test_a_board_without_a_readable_caption_does_not_take_the_one_above():
    boards = [(50, 80, 200, 230), (50, 290, 200, 440)]
    # The top board's caption sits below it (and above the second board); the second has none.
    lines = [_line("121) White to play", 30, 250, 170, 260)]
    assert _diagram_labels(boards, lines) == ["121", None]


def test_captions_joined_into_one_line_by_ocr():
    boards = [(50, 80, 200, 230), (260, 80, 410, 230)]
    lines = [_line("122) White to play 125) Black to play", 30, 250, 390, 260)]
    assert _diagram_labels(boards, lines) == ["122", "125"]


def test_captions_in_the_bottom_margin_are_not_running_footers():
    pages = [[_line(f"{n}) White to play (2 points)", 30, 666, 170, 676), _line(str(n + 300), 200, 690, 220, 700)]
             for n in range(10)]
    running = _running_lines(pages, [(450, 700)] * 10)
    assert "#) white to play (# points)" not in running
    assert "#" in running  # the page numbers are


def test_two_dots_mean_black():
    # No side-to-move mark on the diagram: "1..Ra1#" is Black's move.
    a = analyze(DocStream([Block("diagram", placement="6k1/5ppp/8/8/8/8/r4PPP/6K1"), ocr("1..Ra1#")]))
    g = a.anchored.games[0]
    assert g.start_fen.split()[1] == "b" and [n.san for n in g.mainline()[1:]] == ["Ra1#"]


def test_two_dots_can_still_be_whites_bishop():
    # "..i." is how one book's OCR prints a bishop: "1 ..i.e4" is White's move after all.
    a = analyze(DocStream([Block("diagram", placement="6k1/8/8/8/8/8/8/1B4K1"), ocr("1 ..i.e4")]))
    assert [n.san for n in a.anchored.games[0].mainline()[1:]] == ["Be4"]


def test_garbled_results_are_results():
    assert [t.kind for t in tokenize("1...Qb2+ 0-I 2 Bxb2 I-0", ocr=True)] == ["number", "move", "result", "number", "move", "result"]


def test_an_unreadable_move_is_worked_out_from_the_moves_after_it():
    # "#z#" is Black's 2nd move: only 2...Qxd5 lets 3.Nc3 Qa5 4.d4 Nf6 5.Nf3 c6 follow.
    evs = events(DocStream([ocr("1.e4 d5 2.exd5 #z# 3.Nc3 Qa5 4.d4 Nf6 5.Nf3 c6")]))
    a = anchor(evs, letter_map("en"), "paragraph")
    main = a.games[0].mainline()[1:]
    assert " ".join(n.san for n in main) == "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6 Nf3 c6"
    assert main[3].refs[0].end - main[3].refs[0].start == 3  # the garbled word is that move
    assert main[3].guessed == set(main[3].refs) and not main[4].guessed  # and the reader shows it as a guess


def test_an_unreadable_move_with_many_possibilities_is_left_alone():
    evs = events(DocStream([ocr("1.e4 e5 2.Nf3 #z# 3.Bc4 Bc5")]))
    a = anchor(evs, letter_map("en"), "paragraph")
    assert [n.san for n in a.games[0].mainline()[1:]] == ["e4", "e5", "Nf3"]
    assert all("#z#" not in u.text for u in a.unresolved)


def test_a_diagram_number_split_by_ocr():
    boards = [(70, 160, 196, 288)]
    assert _diagram_labels(boards, [_line("1 08 ", 54, 160, 66, 172)], ocr=True) == ["108"]
    # A move line next to the board is not its number, even when OCR garbled the move.
    assert _diagram_labels(boards, [_line("29 . .icl !", 54, 140, 90, 152)], ocr=True) == [None]


def test_rank_numbers_beside_a_board_are_not_its_number():
    board = (60, 100, 220, 260)  # squares of 20 points
    lines = [_line("8", 46, 102, 54, 114), _line("7", 46, 122, 54, 134), _line("37) White to play", 60, 268, 200, 278)]
    assert _diagram_labels([board], lines, ocr=True) == ["37"]
    # A "3" level with the top rank can't be a coordinate: it is the diagram's number.
    assert _diagram_labels([board], [_line("3", 46, 102, 54, 114)], ocr=True) == ["3"]


def test_captions_with_chapter_numbers_split_by_ocr():
    board = (70, 160, 196, 288)
    for caption, label in (("Diagrama 1 0.1 ", "10.1"), ("Diagrama 1 .1 2 ", "1.12"), ("2.1 0 Juegan negras", "2.10")):
        assert _diagram_labels([board], [_line(caption, 90, 292, 160, 302)], ocr=True) == [label]


def shapes(text: str) -> list[tuple]:
    return [(t.kind, t.text, t.number if t.kind == "number" else None) for t in tokenize(text, ocr=True)]


def test_move_numbers_split_by_a_space():
    # Mi sistema: "1 1.0-0" is move 11, "2 l ..." Black's 21st, "1 O.c4" move 10.
    assert shapes("1 1.0-0 h5")[0] == ("number", "1 1.", 11)
    assert shapes("por 2 l ...ib4.")[0] == ("number", "2 l ...", 21)
    assert shapes("clave 1 O.c4, etc.")[:2] == [("number", "1 O.", 10), ("move", "c4", None)]


def test_squares_split_by_a_space_and_moves_printed_together():
    toks = shapes("1.e4e6 2.d4 d 5 3.e5 e 5")
    assert [t[1] for t in toks] == ["1.", "e4", "e6", "2.", "d4", "d 5", "3.", "e5", "e 5"]
    # The digit after a split file is a move number when a dot follows it ("d 5." is not d5).
    assert ("move", "d 5", None) not in shapes("12.d 5. h6")


def test_a_number_glued_to_its_move_and_a_bracket_that_is_a_bishop():
    toks = tokenize("9.ig3 ig7 10JWe2 Te7", ocr=True)
    assert [(t.kind, t.text) for t in toks][3:5] == [("number", "10J"), ("move", "We2")]
    assert toks[3].number == 10 and toks[3].black is False
    toks = tokenize("4.[g5 8.[xc6+ bxc6", ocr=True)
    assert [t.kind for t in toks] == ["number", "move", "number", "move", "move"]
    assert toks[1].move.piece == "[" and toks[3].move.capture


def test_a_piece_letter_with_its_origin_is_a_move_not_a_word():
    toks = {t.text: t.move for t in tokenize("24.cxd4 Rac8 25.f3 Ree7 18.N1d2 Tad1", ocr=True) if t.kind == "move"}
    assert (toks["Rac8"].piece, toks["Rac8"].from_file) == ("R", 0)
    assert (toks["Ree7"].piece, toks["Ree7"].from_file) == ("R", 4)
    assert (toks["N1d2"].piece, toks["N1d2"].from_rank) == ("N", 0)
    assert toks["Tad1"].piece == "T"
    assert [t.text for t in tokenize("las blancas del final", ocr=True) if t.kind == "move" and not t.move.weak] == []


def test_game_headers_are_names_not_sentences():
    from cbv.ingest.pdf import GAME_HEADER

    for header in ("Nimzovich - Yates", "von Bardeleben - Nisnievich", "Partida n° 1 3", "Nimzovich - N. N."):
        assert GAME_HEADER.match(header), header
    for prose in ("partida Nirnzovich - Freyrnann, (página 79).", "Nirnzovich - Nilsson (página 77)",
                  "nobles sentimientos entre piezas- muestra,", "tida Thomas - Alekhine. La partida siguió así:"):
        assert not GAME_HEADER.match(prose), prose


def test_a_scanned_line_after_a_sentence_starts_a_paragraph():
    from cbv.parse.fragments import _starts_line

    text = "El negro debió jugar 4 ... c5. \n5.Bd3 e6 6.0-0"
    assert _starts_line(text, text.index("5.Bd3"), scanned=True)
    assert not _starts_line(text, text.index("5.Bd3"), scanned=False)
    assert not _starts_line("y luego \n5.Bd3", 10, scanned=True)  # the sentence goes on


def test_a_bare_pawn_move_is_never_a_capture():
    board = chess.Board("4k3/8/8/4P3/3p4/8/8/4K3 b - - 0 1")
    assert candidates(board, ParsedMove(to_square=chess.E4), letter_map("en")) == []  # d4 can't go to e4 without "x"
    assert [board.san(m) for m in candidates(board, ParsedMove(to_square=chess.D3), letter_map("en"))] == ["d3"]


def test_an_origin_glued_to_a_spelling_says_which_piece_moved():
    board = chess.Board("1r3rk1/8/8/8/8/8/8/6K1 b - - 0 1")
    pieces = letter_map("en", {"13": chess.ROOK, "13b": chess.ROOK})
    # "13bc8": the rook from the b-file, though "13b" was learned as a whole spelling too.
    assert [board.san(m) for m in candidates(board, ParsedMove(piece="13b", to_square=chess.C8), pieces)] == ["Rbc8"]
    # A spelling that merely ends in a letter: read whole when the split reading fits nothing.
    board = chess.Board("6k1/8/8/8/8/8/8/R5K1 w - - 0 1")
    pieces = letter_map("en", {"!": chess.ROOK, "!h": chess.ROOK})
    assert [board.san(m) for m in candidates(board, ParsedMove(piece="!h", to_square=chess.A7), pieces)] == ["Ra7"]
