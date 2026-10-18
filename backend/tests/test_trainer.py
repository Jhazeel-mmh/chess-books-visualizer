"""The daily trainer: time split, retries, roles, and sessions built from the books' analyses."""

import json
from datetime import datetime, timedelta, timezone

import chess

from cbv import trainer

NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def ago(days: int) -> str:
    return (NOW - timedelta(days=days)).isoformat()


def test_the_time_split_fills_the_session():
    for minutes in (45, 50, 60):
        blocks = trainer.split(minutes, None)
        assert [b for b, _ in blocks] == ["calculation", "endgame", "reading", "guess"]
        assert sum(m for _, m in blocks) == minutes
    assert dict(trainer.split(45, None))["calculation"] == 18
    assert dict(trainer.split(60, None))["calculation"] == 24


def test_one_focus_gets_more_time():
    plain, focused = dict(trainer.split(60, None)), dict(trainer.split(60, "endgames"))
    assert focused["endgame"] > plain["endgame"] and focused["calculation"] < plain["calculation"]
    positional = dict(trainer.split(60, "positional"))
    assert positional["reading"] > plain["reading"] and positional["guess"] > plain["guess"]


def test_missed_positions_come_back_after_a_week_then_a_month():
    assert not trainer.due([], NOW)
    assert not trainer.due([{"at": ago(30), "result": "full"}], NOW)  # solved the first time: done
    assert not trainer.due([{"at": ago(3), "result": "wrong"}], NOW)
    assert trainer.due([{"at": ago(8), "result": "first"}], NOW)
    solved_again = [{"at": ago(40), "result": "wrong"}, {"at": ago(10), "result": "full"}]
    assert not trainer.due(solved_again, NOW)
    assert trainer.due([{"at": ago(70), "result": "wrong"}, {"at": ago(31), "result": "full"}], NOW)
    assert not trainer.due([{"at": ago(90), "result": "wrong"}, {"at": ago(60), "result": "full"}, {"at": ago(20), "result": "full"}], NOW)


def test_roles_and_difficulty():
    assert trainer.guess_role("Los 100 finales que hay que saber", 66, 316) == "endgames"
    assert trainer.guess_role("1001 Deadly Checkmates", 997, 1018) == "tactics"
    assert trainer.guess_role("Mi sistema", 31, 240) == "concepts"
    assert trainer.difficulty(1, None, None) == 1
    assert trainer.difficulty(5, None, "3. Advanced Exercises") == 4
    assert trainer.difficulty(3, 5, None) == 3.5
    assert trainer.level_for(1600) == 2.5 and trainer.level_for(2000) == 3.5


def line(*sans: str, start: str = chess.STARTING_FEN, prefix: str = "") -> list[dict]:
    """Moves as analysis nodes: a single line from ``start``."""
    board = chess.Board(start)
    nodes = [{"id": f"{prefix}0", "parent": None, "children": [], "san": None, "uci": None, "fen": board.fen(),
              "nags": [], "mainline": True, "refs": []}]
    for i, san in enumerate(sans, 1):
        move = board.parse_san(san)
        board.push(move)
        nodes[-1]["children"] = [f"{prefix}{i}"]
        nodes.append({"id": f"{prefix}{i}", "parent": f"{prefix}{i - 1}", "children": [], "san": san, "uci": move.uci(),
                      "fen": board.fen(), "nags": [], "mainline": True, "refs": []})
    return nodes


def make_book(books, book_id: str, title: str, games: list[list[dict]], diagrams: list[dict], kind="pdf"):
    d = books / book_id
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": book_id, "title": title, "status": "ready", "imported_at": "x"}))
    analysis = {"games": [{"id": f"g{i}", "title": f"Game {i}", "root": g[0]["id"], "nodes": g} for i, g in enumerate(games)],
                "diagrams": diagrams, "sections": []}
    (d / "analysis.json").write_text(json.dumps(analysis))
    layout = {"kind": kind, "blocks": [], "pages": [[400, 600]] * 120} if kind == "pdf" else {"kind": kind, "blocks": [], "chapters": [{}] * 30}
    (d / "layout.json").write_text(json.dumps(layout))
    return json.loads((d / "meta.json").read_text())


MATE = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"  # Rd8#
LONG_GAME = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6", "O-O", "Be7", "Re1", "b5", "Bb3", "d6", "c3", "O-O",
             "h3", "Nb8", "d4", "Nbd7", "c4", "c6", "cxb5", "axb5", "Nc3", "Bb7", "Bg5", "b4", "Nb1", "h6", "Bh4", "c5",
             "dxe5", "Nxe4", "Bxe7", "Qxe7", "exd6", "Qf6", "Nbd2", "Nxd6"]


def test_a_session_mixes_the_books(tmp_path):
    books = tmp_path / "books"
    problems = []
    for i in range(12):
        problems.append(line("Rd8#", start=MATE, prefix=f"p{i}-"))
    tactics = make_book(books, "a" * 40, "Puzzles", problems,
                        [{"id": f"d{i}", "key": f"k{i}", "node": f"p{i}-0", "problem": True, "label": str(i + 1)} for i in range(12)])
    endgame_nodes = line(start="8/8/8/4k3/8/8/4P3/4K3 w - - 0 1", prefix="e")
    endgames = make_book(books, "b" * 40, "Finales básicos", [endgame_nodes],
                         [{"id": "e", "key": "ke", "node": "e0", "problem": False}])
    concepts = make_book(books, "c" * 40, "My System", [line(*LONG_GAME, prefix="c")], [], kind="epub")
    metas = [tactics, endgames, concepts]

    record = trainer.complete({"settings": {"minutes": 45, "rating": 1600}})
    session = trainer.build_session(books, metas, record, now=NOW, seed=1)
    kinds = {b["kind"]: b for b in session["blocks"]}
    assert list(kinds) == ["calculation", "endgame", "reading", "guess"]
    calc = kinds["calculation"]["items"]
    assert len(calc) == 3 and all(it["book"] == "a" * 40 for it in calc)
    assert calc[0]["tree"][0]["children"] and calc[0]["fen"] == chess.Board(MATE).fen()
    assert kinds["endgame"]["items"][0]["book"] == "b" * 40
    reading = kinds["reading"]["items"][0]
    assert reading["book"] in ("b" * 40, "c" * 40) and reading["length"] in (120, 30)
    guess = kinds["guess"]["items"][0]
    assert guess["from"] == trainer.GUESS_START_PLY and len(guess["line"]) == len(LONG_GAME) + 1

    # Seen positions are not given again; a missed one comes back when it is due.
    record["positions"] = {f"{'a' * 40}:k{i}": [{"at": ago(1), "result": "full"}] for i in range(11)}
    record["positions"][f"{'a' * 40}:k0"] = [{"at": ago(8), "result": "wrong"}]
    again = trainer.build_session(books, metas, record, now=NOW, seed=2)
    keys = sorted(it["key"] for it in again["blocks"][0]["items"])
    assert keys == ["k0", "k11"]

    test = trainer.build_session(books, metas, trainer.complete({}), test=True, now=NOW, seed=3)
    assert [b["kind"] for b in test["blocks"]] == ["calculation"] and len(test["blocks"][0]["items"]) == 6
    assert test["blocks"][0]["minutes"] == trainer.TEST_MINUTES


def test_a_skipped_book_gives_nothing(tmp_path):
    books = tmp_path / "books"
    meta = make_book(books, "a" * 40, "Puzzles", [line("Rd8#", start=MATE, prefix="p")],
                     [{"id": "d", "key": "k", "node": "p0", "problem": True}])
    record = trainer.complete({"roles": {"a" * 40: "skip"}})
    assert trainer.build_session(books, [meta], record, now=NOW)["blocks"] == []


def test_the_books_picked_for_each_subject(tmp_path):
    books = tmp_path / "books"
    a, b, c = "a" * 40, "b" * 40, "c" * 40
    metas = [
        make_book(books, a, "Puzzles", [line("Rd8#", start=MATE, prefix=f"p{i}-") for i in range(6)],
                  [{"id": f"d{i}", "key": f"k{i}", "node": f"p{i}-0", "problem": True} for i in range(6)]),
        # A concept book with a few problems: left out of calculation unless picked.
        make_book(books, b, "My System", [line("Rd8#", start=MATE, prefix="q"), line(*LONG_GAME, prefix="g")],
                  [{"id": "dq", "key": "kq", "node": "q0", "problem": True}] + [{"id": f"x{i}", "key": f"x{i}"} for i in range(4)]),
        make_book(books, c, "Strategy", [line(*LONG_GAME, prefix="s")], []),
    ]
    record = trainer.complete({})
    overview = {o["id"]: o for o in trainer.books_overview(books, metas, record)}
    assert overview[a]["uses"]["calculation"] and not overview[b]["uses"]["calculation"]
    assert overview[b]["material"]["calculation"] == 1 and overview[c]["material"]["calculation"] == 0

    # Calculation from the concept book only; guess the move from one book only.
    record["sources"] = {"calculation": [b], "guess": [c]}
    session = trainer.build_session(books, metas, record, now=NOW, seed=1)
    kinds = {blk["kind"]: blk for blk in session["blocks"]}
    assert {it["book"] for it in kinds["calculation"]["items"]} == {b}
    assert kinds["guess"]["items"][0]["book"] == c

    # Nothing picked for a subject: that part is left out.
    record["sources"] = {"calculation": [], "reading": [], "guess": []}
    session = trainer.build_session(books, metas, record, now=NOW, seed=1)
    assert [blk["kind"] for blk in session["blocks"]] == []  # and no endgames in these books

    # A book picked for a subject it has nothing for gives nothing.
    record["sources"] = {"calculation": [c]}
    assert "calculation" not in {blk["kind"] for blk in trainer.build_session(books, metas, record, now=NOW)["blocks"]}


def test_several_reading_books_take_turns(tmp_path):
    books = tmp_path / "books"
    metas = [make_book(books, x * 40, title, [], [], kind="epub") for x, title in (("a", "Alpha"), ("b", "Beta"))]
    record = trainer.complete({"sources": {"reading": ["a" * 40, "b" * 40]}})
    first = trainer.build_session(books, metas, record, now=NOW)["blocks"][0]["items"][0]["book"]
    record["sessions"] = [{"finished": ago(1), "results": [[{"kind": "reading", "book": first, "from": 0, "to": 3}]]}]
    second = trainer.build_session(books, metas, record, now=NOW)["blocks"][0]["items"][0]["book"]
    assert {first, second} == {"a" * 40, "b" * 40}
