import json
import zipfile

import pymupdf
from lxml import etree

from cbv.ingest import open_book
from cbv.parse import analyze

CHAPTER = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><link rel="stylesheet" href="../style.css"/></head>
<body>
<h2>1<br/>Morphy – Duke of Brunswick</h2>
<p class="main">1.e4 e5 2.Nf3 d6</p>
<p>Philidor's Defence. Also possible is 2...Nc6 3.Bb5.</p>
<p class="main">3.d4 <i>Bg4</i>?!</p>
<script>alert(1)</script>
</body></html>"""


def make_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        z.writestr("OEBPS/content.opf", """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0"><manifest>
<item id="c1" href="text/ch%201.xhtml" media-type="application/xhtml+xml"/>
<item id="css" href="style.css" media-type="text/css"/>
</manifest><spine><itemref idref="c1"/></spine></package>""")
        z.writestr("OEBPS/style.css", "p.main { font-weight: bold }")
        z.writestr("OEBPS/text/ch 1.xhtml", CHAPTER)


def test_epub_blocks_bold_and_annotated_chapter(tmp_path):
    make_epub(tmp_path / "book.epub")
    book = open_book(tmp_path / "book.epub")
    blocks = book.doc.blocks
    assert [b.kind for b in blocks] == ["heading", "para", "para", "para"]
    assert blocks[0].game_header
    assert blocks[1].is_bold(0, 4) and not blocks[2].is_bold(0, 10)

    result = analyze(book.doc)
    lines = [n.san for n in result.anchored.games[0].mainline()[1:]]
    assert lines == ["e4", "e5", "Nf3", "d6", "d4", "Bg4"]

    layout = book.export(tmp_path, result.marks())
    assert layout["chapters"][0]["href"] == "OEBPS/text/ch 1.xhtml"
    out = etree.parse(str(tmp_path / "epub/OEBPS/text/ch 1.xhtml"))
    spans = list(out.getroot().iterfind(".//{http://www.w3.org/1999/xhtml}span[@data-cbv-node]"))
    # "<i>Bg4</i>?!" is one move split over two text nodes: two spans for the same node.
    assert ["".join(s.itertext()) for s in spans] == ["1.e4", "e5", "2.Nf3", "d6", "2...Nc6", "3.Bb5", "3.d4", "Bg4", "?!"]
    assert spans[-1].get("data-cbv-node") == spans[-2].get("data-cbv-node")
    assert not list(out.getroot().iter("{*}script"))


def test_pdf_blocks_marks_and_headers(tmp_path):
    pdf = pymupdf.open()
    for n in range(4):  # a running header and page numbers on every page
        page = pdf.new_page(width=400, height=600)
        page.insert_text((40, 20), "MY CHESS BOOK", fontsize=8)
        page.insert_text((190, 590), str(n + 1), fontsize=8)
        if n == 0:
            page.insert_text((40, 100), "1.e4 e5 2.Nf3 Nc6 3.Bb5", fontsize=11)
            page.insert_text((40, 114), "a6 4.Ba4 Nf6", fontsize=11)
    pdf.save(tmp_path / "book.pdf")

    book = open_book(tmp_path / "book.pdf")
    texts = [b.text for b in book.doc.blocks]
    assert not any("MY CHESS BOOK" in t for t in texts)
    result = analyze(book.doc)
    assert [n.san for n in result.anchored.games[0].mainline()[1:]] == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]

    layout = book.export(tmp_path, result.marks())
    assert layout["pages"][0] == [400, 600]
    marks = json.loads((tmp_path / "pages/0.json").read_text())
    rects = [m["rects"][0] for m in marks if m["kind"] == "move"]
    assert len(rects) == 8
    assert all(40 <= r[0] < r[2] < 400 and 80 < r[1] < r[3] < 120 for r in rects)
