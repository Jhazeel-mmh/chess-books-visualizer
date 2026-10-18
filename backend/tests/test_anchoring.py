import chess

from cbv.parse import analyze
from cbv.ingest.model import Block
from tests.helpers import cont, diagram, doc, header


def lines(analysis, game=0):
    """Every root-to-leaf line of a game as space-separated SAN, main line first."""
    g = analysis.anchored.games[game]
    out = []

    def walk(node, sans):
        if not node.children:
            out.append(" ".join(sans))
        for child in node.ordered_children():
            walk(child, sans + [child.san])

    walk(g.root, [])
    return out


def test_main_line_with_parenthesised_variation():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5 (3.Bc4 Bc5 4.c3) 3...a6 4.Ba4 Nf6"))
    assert lines(a) == [
        "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6",
        "e4 e5 Nf3 Nc6 Bc4 Bc5 c3",
    ]
    assert a.anchored.unresolved == []


def test_variation_without_brackets_returns_to_main_line():
    a = analyze(doc(
        "**1.e4 e5 2.Nf3 Nc6 3.Bb5 a6**",
        "Instead 3...Nf6 4.O-O is the Berlin.",
        "**4.Ba4 Nf6 5.O-O**",
    ))
    assert lines(a)[0] == "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O"
    assert "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O" in lines(a)


def test_comment_between_moves_continues_the_line():
    a = analyze(doc("1.d4 d5 2.c4 The Queen's Gambit. 2...e6 3.Nc3 Nf6"))
    assert lines(a) == ["d4 d5 c4 e6 Nc3 Nf6"]


def test_mentioning_a_move_again_links_to_the_same_node():
    a = analyze(doc("1.e4 c5 2.Nf3 d6", "The move 2.Nf3 is the most common."))
    g = a.anchored.games[0]
    nf3 = g.root.children[0].children[0].children[0]
    assert nf3.san == "Nf3" and len(nf3.refs) == 2
    assert lines(a) == ["e4 c5 Nf3 d6"]


def test_bare_variation_inside_brackets_is_an_alternative():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 (Nf6 3.Nxe5) 3.Bb5"))
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5", "e4 e5 Nf3 Nf6 Nxe5"]


def test_spanish_book_is_detected():
    a = analyze(doc("1.e4 e5 2.Cf3 Cc6 3.Ab5 a6 4.Aa4 Cf6 5.O-O Ae7 6.Te1 b5 7.Ab3 d6 8.c3 O-O"))
    assert a.pieces.lang == "es"
    assert lines(a)[0].endswith("Bb3 d6 c3 O-O")


def test_unknown_chess_font_glyphs_are_resolved_by_legality():
    # A chess font whose glyphs ingestion mapped to private-use codepoints.
    glyph = {"K": "", "Q": "", "R": "", "B": "", "N": ""}
    game = ("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 5.O-O Be7 6.Re1 b5 7.Bb3 d6 8.c3 O-O "
            "9.h3 Nb8 10.d4 Nbd7 11.Nbd2 Bb7 12.Bc2 Re8 13.Nf1 Bf8 14.Ng3 g6 15.Qd2 Qe7 16.Kh2")
    a = analyze(doc(game.translate(str.maketrans(glyph))))
    assert a.pieces.has_glyphs
    assert a.pieces.describe()["glyphs"] == {"U+E010": "K", "U+E011": "Q", "U+E012": "R", "U+E013": "B", "U+E014": "N"}
    assert lines(a)[0].endswith("Qd2 Qe7 Kh2")


def test_heading_starts_a_new_game():
    a = analyze(doc(
        "# Game 1: Anderssen – Kieseritzky",
        "1.e4 e5 2.f4 exf4 1-0",
        "# Game 2",
        "1.d4 d5 2.c4",
    ))
    games = a.anchored.games
    assert [g.title for g in games] == ["Game 1: Anderssen – Kieseritzky", "Game 2"]
    assert lines(a, 1) == ["d4 d5 c4"]


def test_illegal_move_is_unresolved_with_what_depends_on_it():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb6 a6 4.Bc4 Nf6"))
    assert [(u.text, u.reason) for u in a.anchored.unresolved] == [
        ("3.Bb6 a6", "illegal"),
        ("4.Bc4 Nf6", "no_position"),
    ]
    assert lines(a) == ["e4 e5 Nf3 Nc6"]


def test_repeated_move_number_starts_a_new_variation():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 3.Bc4 Bc5"))
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5 a6", "e4 e5 Nf3 Nc6 Bc4 Bc5"]
    assert a.anchored.unresolved == []


def test_fragment_without_context_is_unresolved():
    a = analyze(doc("34.Rxf7+ Kxf7 35.Qh5+"))
    assert a.anchored.games == []
    assert a.anchored.unresolved[0].reason == "no_game"


def test_pgn_export_has_variations_and_nags():
    a = analyze(doc("1.e4 e5 2.Nf3! (2.f4!? exf4) 2...Nc6"))
    pgn = a.anchored.games[0].to_pgn()
    assert "2. Nf3 $1" in pgn and "( 2. f4 $5 exf4 )" in pgn
    game = chess.pgn.read_game(__import__("io").StringIO(pgn))
    assert game.end().board().fen().startswith("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2")


def test_fragment_runs_on_across_lines_of_one_paragraph():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5", cont("a6 4.Ba4"), cont("Nf6 5.")))
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6"]
    # A new paragraph does not continue the fragment: a bare move there is prose.
    b = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5", "a6 4.Ba4"))
    assert lines(b) == ["e4 e5 Nf3 Nc6 Bb5"]


def test_moves_after_a_diagram_start_from_its_position():
    # Puzzle: White mates in two from the diagram (Black to move is impossible: White is not in check).
    a = analyze(doc(diagram("6k1/5ppp/8/8/8/8/5PPP/3R2K1"), "1.Rd8#"))
    g = a.anchored.games[0]
    assert g.start_fen.startswith("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w")
    assert lines(a) == ["Rd8#"]
    assert a.anchored.diagram_nodes[0] is g.root


def test_diagram_mid_game_links_to_the_existing_position():
    a = analyze(doc("1.e4 e5 2.Nf3", diagram("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R"), "2...Nc6 3.Bb5"))
    assert len(a.anchored.games) == 1
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5"]
    assert a.anchored.diagram_nodes[1].san == "Nf3"


def test_game_header_ends_the_previous_game():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4", header("Karpov – Kasparov, Moscow 1985"), "4...Nf6"))
    assert [u.reason for u in a.anchored.unresolved] == ["no_game"]


def test_numbered_solution_starts_from_the_diagram_with_that_number():
    a = analyze(doc(
        diagram("6k1/5ppp/8/8/8/8/5PPP/3R2K1", label="7"),
        diagram("r5k1/5ppp/8/8/8/8/5PPP/6K1", label="8"),
        "# Solutions",
        header("8. Smith – Jones, London 1900"),
        "30...Ra1# The back rank again.",
        header("7. Jones – Smith, Paris 1901"),
        "25.Rd8#",
    ))
    games = a.anchored.games
    assert [g.root.children[0].san for g in games] == ["Ra1#", "Rd8#"]
    assert games[0].start_fen.endswith("b - - 0 30")
    assert a.anchored.diagram_nodes == {1: games[0].root, 0: games[1].root}


def test_a_move_number_is_not_a_reference():
    a = analyze(doc(diagram("6k1/5ppp/8/8/8/8/5PPP/3R2K1", label="1"), "Game:", "1. e4 e5"))
    assert [n.san for n in a.anchored.games[0].mainline()[1:]] == ["e4", "e5"]


def test_solution_list_with_number_then_moves():
    # Polgar-style solutions: "<problem number> <moves from move 1>".
    a = analyze(doc(diagram("6k1/5ppp/8/8/8/8/5PPP/3R2K1", label="1"), "# Solutions", cont("1 1.Rd8#")))
    assert a.anchored.diagram_nodes[0] is a.anchored.games[0].root


def test_a_reply_after_a_side_line_answers_the_main_move():
    # "3.Bb5! 3.Bc4 Bc5 4.c3 …" then "3...a6": a6 answers 3.Bb5, the move still waiting for a reply,
    # not 3.Bc4 from the side line just read.
    a = analyze(doc(
        "1.e4 e5 2.Nf3 Nc6 3.Bb5! The alternative 3.Bc4 Bc5 4.c3 is the Italian. 3...a6 is the Morphy Defence.",
        "4.Ba4 Nf6",
    ))
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3"]


def test_an_alternative_to_the_move_just_read_stays_its_sibling():
    a = analyze(doc("1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6 Also good is 4...d6 5.c3"))
    assert lines(a) == ["e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 d6 c3"]


def test_a_misread_square_is_corrected_by_the_solution():
    # d1 was read as a bishop, though the network thought a rook or a queen likely too: only a rook
    # there lets the printed solution 1.Rd8# be played (and mate).
    misread = Block("diagram", placement="6k1/5ppp/8/8/8/8/5PPP/3B2K1", alternatives={59: "RQ"})
    a = analyze(doc(misread, "1.Rd8#"))
    assert a.anchored.diagram_fixes == {0: "6k1/5ppp/8/8/8/8/5PPP/3R2K1"}
    d = a.diagrams()[0]
    assert d["placement"] == "6k1/5ppp/8/8/8/8/5PPP/3R2K1" and d["fixed"] and d["check"] == ["fixed"]
    assert [n.san for n in a.anchored.games[0].mainline()[1:]] == ["Rd8#"]


def test_a_diagram_is_not_corrected_when_several_readings_fit():
    # The rook may be on a1 or on h1: "1.Re1 h6 2.Re8+" works from either, so the solution can't tell.
    misread = Block("diagram", placement="6k1/5ppp/8/8/8/8/5PPK/8", alternatives={56: "R", 63: "R"})
    a = analyze(doc(misread, "1.Re1 h6 2.Re8+"))
    assert a.anchored.diagram_fixes == {}
    assert a.diagrams()[0]["check"] == ["solution_failed"]


def test_side_to_move_comes_from_the_moves_and_marks_read_the_books_way():
    # A book whose marks say Black while every solution is White's: its marks mean the opposite.
    blocks = []
    for _ in range(10):
        blocks += [Block("diagram", placement="6k1/5ppp/8/8/8/8/5PPP/3R2K1", turn="b"), "1.Rd8#"]
    blocks.append(Block("diagram", placement="6k1/5ppp/8/8/8/8/5PPP/2R3K1", turn="b"))
    diagrams = analyze(doc(*blocks)).diagrams()
    assert [d["turn"] for d in diagrams] == ["w"] * 11
