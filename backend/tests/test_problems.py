"""Which diagrams are problems to solve, and where their solutions start."""

from cbv.ingest.model import Block, DocStream
from cbv.ingest.pdf import _caption
from cbv.parse import _section_kind, analyze
from tests.helpers import cont, diagram, doc, header
from tests.test_ocr import _line

BOARD = (60, 100, 220, 260)
MATE_IN_ONE = "6k1/5ppp/8/8/8/8/5PPP/3R2K1"


def test_captions_that_set_a_task():
    assert _caption(BOARD, [_line("415) White to play (3 points)", 60, 268, 220, 278)]) == ("w", True, 3)
    assert _caption(BOARD, [_line("2.01 Juegan negras", 60, 268, 220, 278), _line("¿Es tablas?", 60, 280, 140, 290)]) == ("b", True, None)
    assert _caption(BOARD, [_line("EJERCICIO (Nivel de dificultad 3)", 60, 70, 220, 80)])[1] is True
    # A move with a question mark under a board is commentary, not a task.
    assert _caption(BOARD, [_line("13.Nf3?", 60, 268, 120, 278)]) == (None, False, None)


def test_section_titles():
    assert _section_kind("1. Easy Exercises") == "problems"
    assert _section_kind("4. Solutions to Easy Exercises") == "solutions"
    assert _section_kind("Mate en dos jugadas") == "problems"
    assert _section_kind("Chapter I Pieces cut off from the play") is None
    assert _section_kind("El problema del bloqueo") is None
    assert _section_kind("Problemas de mate") == "problems"


def test_a_numbered_diagram_is_a_problem_and_its_solution_starts_at_it():
    a = analyze(doc(diagram(MATE_IN_ONE, label="7"), "Something to read.", "# Solutions", cont("7) 1.Rd8#")))
    d = a.diagrams()[0]
    assert d["problem"] and d["solution"] == a.anchored.games[0].root.id


def test_a_task_caption_or_an_exercise_section_makes_a_problem():
    task = Block("diagram", placement=MATE_IN_ONE, task=True, points=2)
    plain = Block("diagram", placement=MATE_IN_ONE)
    a = analyze(DocStream([task, plain]))
    assert [d["problem"] for d in a.diagrams()] == [True, False]
    assert a.diagrams()[0]["points"] == 2 and a.diagrams()[0]["solution"] is None  # the engine will judge it

    sections = DocStream([plain, Block("diagram", placement=MATE_IN_ONE)], sections=[(1, "2. Intermediate Exercises")])
    assert [d["problem"] for d in analyze(sections).diagrams()] == [False, True]
    assert analyze(sections).diagrams()[1]["section"] == "2. Intermediate Exercises"


def test_no_problems_in_solutions_or_on_illustrations():
    in_solutions = DocStream([Block("diagram", placement=MATE_IN_ONE, task=True)], sections=[(0, "Solutions")])
    assert analyze(in_solutions).diagrams()[0]["problem"] is False
    pawns_only = Block("diagram", placement="8/pp3ppp/2p5/3p4/3P4/8/PP3PPP/8", task=True)
    assert analyze(DocStream([pawns_only])).diagrams()[0]["problem"] is False


def test_games_are_not_problems():
    a = analyze(doc(header("Karpov – Kasparov"), "1.e4 c5 2.Nf3 d6", diagram("rnbqkbnr/pp2pppp/3p4/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R"), "3.d4"))
    assert a.diagrams()[0]["problem"] is False
