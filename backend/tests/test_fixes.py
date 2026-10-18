"""Moves the reader fixes on a PDF page: replaced, added where the text is missing, or removed."""

import json

import chess
import pymupdf

from cbv.ingest import open_book
from cbv.parse import analyze

AFTER_NF3 = "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2"


def book(tmp_path, line: str):
    pdf = pymupdf.open()
    page = pdf.new_page(width=400, height=600)
    page.insert_text((40, 100), line, fontsize=11)
    path = tmp_path / "book.pdf"
    pdf.save(path)
    return path


def box(path, text: str) -> list[float]:
    with pymupdf.open(path) as pdf:
        r = pdf[0].search_for(text)[0]
    return [r.x0, r.y0, r.x1, r.y1]


def mainline(result) -> list[str]:
    return [n.san for n in result.anchored.games[0].mainline()[1:]]


def test_a_garbled_move_fixed_by_the_reader_lets_the_game_go_on(tmp_path):
    path = book(tmp_path, "1.e4 e5 2.Nf3 ltlc6? 3.Bb5 a6 4.Ba4 Nf6")
    assert mainline(analyze(open_book(path).doc)) == ["e4", "e5", "Nf3"]

    pdf_book = open_book(path)
    pdf_book.place_fixes([{"page": 0, "rect": box(path, "ltlc6?"), "before": AFTER_NF3, "uci": "b8c6"}])
    result = analyze(pdf_book.doc)
    assert mainline(result) == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]
    pdf_book.export(tmp_path, result.marks())
    marks = json.loads((tmp_path / "pages/0.json").read_text())
    assert sum(1 for m in marks if m.get("fixed")) == 1


def test_a_move_missing_from_the_text_is_added_where_the_reader_drew_it(tmp_path):
    path = book(tmp_path, "1.e4 e5 2.Nf3           3.Bb5 a6")
    nf3, bb5 = box(path, "2.Nf3"), box(path, "3.Bb5")
    gap = [nf3[2] + 4, nf3[1], bb5[0] - 4, nf3[3]]  # the empty space where Nc6 should be
    pdf_book = open_book(path)
    pdf_book.place_fixes([{"page": 0, "rect": gap, "before": AFTER_NF3, "uci": "b8c6"}])
    result = analyze(pdf_book.doc)
    assert mainline(result) == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    pdf_book.export(tmp_path, result.marks())
    fixed = [m for m in json.loads((tmp_path / "pages/0.json").read_text()) if m.get("fixed")]
    (x0, y0, x1, y1), = fixed[0]["rects"]
    assert gap[0] - 2 <= x0 < x1 <= gap[2] + 2  # highlighted where the reader drew it


def test_a_false_move_can_be_removed(tmp_path):
    path = book(tmp_path, "1.e4 e5 2.Nf3 Nc6 3.Bb5")
    pdf_book = open_book(path)
    pdf_book.place_fixes([{"page": 0, "rect": box(path, "Nc6"), "remove": True}])
    assert mainline(analyze(pdf_book.doc)) == ["e4", "e5", "Nf3"]


def test_a_fix_from_a_position_the_book_never_reached_starts_a_line_there(tmp_path):
    path = book(tmp_path, "Some text, then Xx5 and 2.Bb5 a6")
    pdf_book = open_book(path)
    before = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 2")
    pdf_book.place_fixes([{"page": 0, "rect": box(path, "Xx5"), "before": before.fen(), "uci": "f1c4"}])
    result = analyze(pdf_book.doc)
    assert [n.san for n in result.anchored.games[0].mainline()[1:]] == ["Bc4"]


def test_a_removed_word_in_a_scan_is_not_worked_out_again():
    from cbv.ingest.model import Block, DocStream, MoveFix
    from cbv.notation.pieces import letter_map
    from cbv.parse.anchoring import anchor
    from cbv.parse.fragments import events

    # Without the fix, "#z#" is worked out as 2...Qxd5 from the moves after it.
    text = "1.e4 d5 2.exd5 #z# 3.Nc3 Qa5"
    block = Block("para", text, ocr=True)
    start = text.index("#z#")
    block.fixes.append(MoveFix(start, start + 3, None, None))
    a = anchor(events(DocStream([block])), letter_map("en"), "paragraph")
    assert "Qxd5" not in [n.san for n in a.games[0].mainline()[1:]]


def test_a_fix_in_a_scan_is_marked_as_the_readers_not_as_a_guess():
    from cbv.ingest.model import Block, DocStream, MoveFix
    from cbv.parse import analyze

    text = "1.e4 d5 2.exd5 #z# 3.Nc3 Qa5"
    block = Block("para", text, ocr=True)
    start = text.index("#z#")
    before = "rnbqkbnr/ppp1pppp/8/3P4/8/8/PPPP1PPP/RNBQKBNR b KQkq - 0 2"
    block.fixes.append(MoveFix(start, start + 3, "d8d5", before))
    result = analyze(DocStream([block]))
    assert [n.san for n in result.anchored.games[0].mainline()[1:]] == ["e4", "d5", "exd5", "Qxd5", "Nc3", "Qa5"]
    (mark,) = [m for m in result.marks() if m.kind == "move" and m.ref.start == start]
    assert mark.fixed and not mark.uncertain
