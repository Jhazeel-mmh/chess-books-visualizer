"""PDF books: positioned text from PyMuPDF, with chess fonts decoded.

Every character keeps its box on the page, so whatever the parser finds can be
highlighted on the rendered page. Text set in chess fonts is either a typed
diagram (decoded to a FEN placement) or figurines inside move text.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from array import array
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pymupdf

from ..notation.pieces import GLYPH_FIRST, GLYPH_LAST
from ..notation.tokenizer import tokenize
from .chessfonts import CHESS_FONT, TABLES, GlyphMapper, TypedRow, decode_row, placement, unsymbol
from .model import Block, DocStream, Mark, MoveFix

if TYPE_CHECKING:
    from ..vision.recognize import ReadBoard

_TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
_BOLD_FONT = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
_NO_BOX = (math.nan,) * 4

# "Karpov – Kasparov, Moscow 1985", "165. Anatoly Karpov – Alexei Shirov", "Partida n° 45".
# "Nimzovich - Yates", "von Bardeleben - Nisnievich", "Partida n° 12". Names are capitalized and the
# dash stands between spaces; not a sentence ("partida Nirnzovich - Freyrnann, (página 79).") nor a
# word broken at the end of a line ("piezas- muestra,").
_PARTICLE = r"(?:von|van|de|der|den|da|di|du|le|la|ten|ter)\s"
GAME_HEADER = re.compile(
    rf"""^\s*(?:\d{{1,4}}[.)]?\s+)?
        (?-i:(?:{_PARTICLE})?[A-ZÁÉÍÓÚÑÖÜ][\w'’.\-]*\s?){{1,4}}\s[–—-]\s(?-i:(?:{_PARTICLE})?[A-ZÁÉÍÓÚÑÖÜ]|N\.\s?N)
        (?!.*\b(?:p[áa]ginas?|pages?)\b)(?![^\n]*(?:[,;:]|[a-záéíóúñ\d)]\.)\s*$)
      | ^\s*(?:partida|game|juego|ejemplo)\s+(?:n\s?[°º.o]?\s*)?\d+""",
    re.VERBOSE | re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(r"^\s*(\d{1,4}|[ivxlcdm]{1,6})\s*$", re.IGNORECASE)
# A diagram's number: "49", "1699", "499) White to play", "2.05 Juegan blancas", "Diagrama 1.25".
# OCR reads ")" as "}" and may split a number ("1 05" for 105, "2.1 0" for 2.10).
_LABEL = re.compile(r"""^\s*(?:
    diagrama?\s+(?P<captioned>\d(?:\s?\d){0,2}(?:\s?\.\s?\d(?:\s?\d)?)?)   # "Diagrama 1 0.1 2": spaces are OCR's
  | (?P<number>\d{1,2}\.\d\s?\d|\d{1,2}\s\d{2}(?!\d)|\d{1,4})\s*[.)}]?(?:\s|$))""", re.VERBOSE | re.IGNORECASE)
# A numbered caption: "123) Black to play (2 points)".
_CAPTION = re.compile(r"^\s*\d{1,4}\s*[)}]\s+\S")
# A second caption further along the same line ("… 125) White to play").
_LABEL_MORE = re.compile(r"(?<=\s)(\d{1,4})[)}](?=\s)")
# Text that OCR laid over a scan: Tesseract's invisible font, or the fonts Acrobat ClearScan draws.
_OCR_FONT = re.compile(r"^(?:[A-Z]{6}\+)?(?:GlyphLessFont|Fd\d+-)")


@dataclass
class PdfSource:
    page: int
    # Four floats (x0, y0, x1, y1) per character of the block's text; NaN for joins.
    boxes: array = field(default_factory=lambda: array("f"))
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class _Line:
    block: int  # PyMuPDF block number on the page
    text: str
    boxes: array
    bold: list[tuple[int, int]]
    size: float
    bbox: tuple[float, float, float, float]
    row: TypedRow | None = None
    # For typed ranks: the box of the 8 square glyphs alone (no border or coordinates).
    squares: tuple[float, float, float, float] | None = None


@dataclass
class _Board:
    rows: list[_Line]
    bbox: tuple[float, float, float, float]
    placement: str | None


@dataclass
class _ImageBoard:
    """A diagram read from an image (embedded picture or scanned page)."""

    bbox: tuple[float, float, float, float]  # in PDF points
    # What was read; consulted only once the whole book is read (the book-level check may change it).
    board: ReadBoard


class PdfBook:
    format = "pdf"

    def __init__(self, path: Path, cache: Path | None = None, progress=None, read_only: bool = False):
        from ..vision.recognize import BoardCache

        self.path = path
        boards_cache = BoardCache(cache, read_only)
        mapper = GlyphMapper()
        with pymupdf.open(path) as pdf:
            self.page_sizes = [(p.rect.width, p.rect.height) for p in pdf]
            self.toc = [[level, title, page - 1] for level, title, page, *_ in pdf.get_toc() if page >= 1]
            pages = []
            for p in pdf:
                if progress and p.number % 10 == 0:
                    progress(p.number / pdf.page_count)
                lines = _page_lines(p, mapper)
                typed = [b.bbox for b in _group_boards(lines)]
                pages.append((lines, _image_boards(p, typed, boards_cache), _ocr_page(p)))
        boards_cache.save()
        running = _running_lines([lines for lines, _, _ in pages], self.page_sizes)
        sizes = [ln.size for lines, _, _ in pages for ln in lines if not ln.row]
        body = statistics.median(sizes) if sizes else 10.0

        blocks: list[Block] = []
        for n, (lines, images, ocr) in enumerate(pages):
            lines = [ln for ln in lines if ln.row or not _in_margin(ln, self.page_sizes[n]) or _running_key(ln.text) not in running]
            page_blocks = _page_blocks(n, lines, images, body, self.page_sizes[n], ocr)
            for b in page_blocks:
                b.ocr = ocr and b.kind != "diagram"
            blocks.extend(page_blocks)
        self.doc = DocStream(blocks, _sections(self.toc, blocks))

    def place_fixes(self, fixes: list[dict]) -> None:
        """Puts the reader's move fixes into the text: ``{page, rect, uci, before}`` or ``{page, rect, remove}``.

        The characters inside the box are the span the fix replaces. When the box holds no text (the
        scan's OCR dropped the move), the fix goes in after the last character printed before it.
        """
        for fix in fixes:
            x0, y0, x1, y1 = fix["rect"]
            on_page = [(i, b) for i, b in enumerate(self.doc.blocks) if b.kind != "diagram" and b.source.page == fix["page"]]
            inside: dict[int, list[int]] = {}
            before = None  # (reading-order key, block, char) of the last character printed before the box
            for i, block in on_page:
                boxes = block.source.boxes
                for c in range(len(block.text)):
                    bx0, by0, bx1, by1 = boxes[4 * c:4 * c + 4]
                    if math.isnan(bx0):
                        continue
                    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
                    if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
                        inside.setdefault(i, []).append(c)
                    elif (by1 <= y0 + 2 or (cy >= y0 and cy <= y1 and bx1 <= x0 + 1)) and (before is None or (cy, bx1) > before[0]):
                        before = ((cy, bx1), i, c)
            if inside:
                i, chars = max(inside.items(), key=lambda kv: len(kv[1]))
                start, end = min(chars), max(chars) + 1
            elif before:
                _, i, c = before
                start = end = c + 1
            elif on_page:
                i, start, end = on_page[0][0], 0, 0
            else:
                continue
            uci = None if fix.get("remove") else fix.get("uci")
            self.doc.blocks[i].fixes.append(MoveFix(start, end, uci, fix.get("before"), tuple(fix["rect"])))

    def export(self, out: Path, marks: list[Mark]) -> dict:
        """Writes per-page highlight boxes to ``out/pages/<n>.json`` and returns the layout."""
        per_page: dict[int, list[dict]] = {}
        for mark in marks:
            block = self.doc.blocks[mark.ref.block]
            src: PdfSource = block.source
            rects = [src.bbox] if block.kind == "diagram" else _rects(src.boxes, mark.ref.start, mark.ref.end)
            if not rects and mark.fixed:
                # A move the reader added where the scan had no text: the box the reader drew.
                rects = [[round(v, 1) for v in f.rect] for f in block.fixes if f.start == mark.ref.start and f.rect]
            if rects:
                item = {"kind": mark.kind, "id": mark.id, "rects": rects}
                if mark.uncertain:
                    item["uncertain"] = True
                if mark.fixed:
                    item["fixed"] = True
                per_page.setdefault(src.page, []).append(item)
        pages_dir = out / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        for old in pages_dir.glob("*.json"):
            old.unlink()
        for n, items in per_page.items():
            (pages_dir / f"{n}.json").write_text(json.dumps(items), encoding="utf-8")
        return {
            "kind": "pdf",
            "pages": [[round(w, 1), round(h, 1)] for w, h in self.page_sizes],
            "toc": self.toc,
            "blocks": [b.source.page for b in self.doc.blocks],
        }


# The largest page image rendered: a page may say it is huge (a PDF page can be 5 m wide).
MAX_PIXELS = 25_000_000


def render_page(path: Path, page: int, zoom: float) -> bytes:
    with pymupdf.open(path) as pdf:
        area = max(1.0, pdf[page].rect.width * pdf[page].rect.height)
        zoom = min(zoom, math.sqrt(MAX_PIXELS / area))
        pix = pdf[page].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")


def _page_lines(page: pymupdf.Page, mapper: GlyphMapper) -> list[_Line]:
    out = []
    for bno, b in enumerate(page.get_text("rawdict", flags=_TEXT_FLAGS)["blocks"]):
        for line in b.get("lines", []):
            text, boxes, bold, sizes = [], array("f"), [], Counter()
            other, raw_chess, chess_boxes = "", [], []
            for span in line["spans"]:
                chars = span["chars"]
                if not chars:
                    continue
                raw = "".join(c["c"] for c in chars)
                start = sum(len(t) for t in text)
                if CHESS_FONT.search(span["font"]):
                    raw_chess.append(raw)
                    chess_boxes.extend(c["bbox"] for c in chars)
                    raw = mapper.figurine_text(raw)
                else:
                    other += raw.strip()
                    # Symbol glyphs of ordinary fonts (Wingdings…) must not look like chess-font glyphs.
                    raw = "".join("•" if GLYPH_FIRST <= ord(c) <= GLYPH_LAST else c for c in raw)
                text.append(raw)
                for c in chars:
                    boxes.extend(c["bbox"])
                if span["flags"] & 16 or _BOLD_FONT.search(span["font"]):
                    bold.append((start, start + len(raw)))
                sizes[round(span["size"], 1)] += len(raw.strip())
            if not text:
                continue
            # A typed rank may share its line with a coordinate label in an ordinary font.
            row = decode_row("".join(raw_chess)) if raw_chess and len(other) <= 1 else None
            squares = None
            if row:
                table = TABLES[row.table]
                sq = [b for ch, b in zip(unsymbol("".join(raw_chess)), chess_boxes) if ch in table]
                squares = (min(b[0] for b in sq), min(b[1] for b in sq), max(b[2] for b in sq), max(b[3] for b in sq))
            size = sizes.most_common(1)[0][0] if sizes else 0.0
            out.append(_Line(bno, "".join(text), boxes, bold, size, _visible_bbox(line), row, squares))
    return out


def _visible_bbox(line: dict) -> tuple[float, float, float, float]:
    """The line's box without trailing control characters (PyMuPDF counts a newline's advance)."""
    boxes = [c["bbox"] for s in line["spans"] for c in s["chars"] if c["c"] >= " " and c["bbox"][2] > c["bbox"][0]]
    if not boxes:
        return tuple(line["bbox"])
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _image_boards(page: pymupdf.Page, typed: list[tuple], cache) -> list[_ImageBoard]:
    """Diagrams inside the page's images: separate pictures, columns of them, or whole scans."""
    from ..vision.recognize import read_boards

    found: list[_ImageBoard] = []
    page_rect = page.rect
    for info in page.get_image_info():
        rect = pymupdf.Rect(info["bbox"]) & page_rect
        if rect.width < 50 or rect.height < 50:
            continue
        if any(_overlap_ratio(tuple(rect), t) > 0.5 for t in typed):
            continue
        # Twice the PDF size is plenty: squares end up 20-60 pixels wide, then shrink to 32.
        zoom = 2.0

        def read(rect=rect, zoom=zoom):
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect, colorspace=pymupdf.csGRAY)
            gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
            return read_boards(gray, min_size=int(40 * zoom))

        key = f"{page.number}:{rect.x0:.0f},{rect.y0:.0f},{rect.x1:.0f},{rect.y1:.0f}"
        for b in cache.read(key, read):
            x0, y0, x1, y1 = b.box
            bbox = (rect.x0 + x0 / zoom, rect.y0 + y0 / zoom, rect.x0 + x1 / zoom, rect.y0 + y1 / zoom)
            if any(_overlap_ratio(bbox, f.bbox) > 0.5 for f in found):
                continue
            found.append(_ImageBoard(bbox, b))
    return sorted(found, key=lambda f: (f.bbox[1], f.bbox[0]))


def _sections(toc: list, blocks: list[Block]) -> list[tuple[int, str]]:
    """The table of contents as (first block, title), unless it is junk (scans list page names)."""
    titles = [title for _, title, _ in toc]
    if not titles or len(set(titles)) < 0.8 * len(titles):
        return []
    sections = []
    for _, title, page in toc:
        first = next((i for i, b in enumerate(blocks) if b.source.page >= page), None)
        if first is not None:
            sections.append((first, " ".join(title.split())))
    return sorted(sections)


def _ocr_page(page: pymupdf.Page) -> bool:
    """True for a scanned page whose text came from OCR."""
    if any(_OCR_FONT.match(font[3]) for font in page.get_fonts()):
        return True
    area = page.rect.get_area()
    return any((pymupdf.Rect(i["bbox"]) & page.rect).get_area() > 0.8 * area for i in page.get_image_info())


def _overlap_ratio(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / smaller if smaller > 0 else 0.0


def _running_key(text: str) -> str:
    return re.sub(r"\d+", "#", " ".join(text.lower().split()))


def _in_margin(line: _Line, size: tuple[float, float]) -> bool:
    h = size[1]
    return line.bbox[1] < 0.08 * h or line.bbox[3] > 0.92 * h


def _running_lines(pages: list[list[_Line]], sizes: list[tuple[float, float]]) -> set[str]:
    """Running headers/footers and page numbers: margin lines repeated across pages."""
    counts: Counter[str] = Counter()
    for lines, size in zip(pages, sizes):
        # Typed diagram ranks ("Z0Z0Z0Z0") and captions ("123) Black to play") repeat on many pages
        # too, but are never headers.
        counts.update({_running_key(ln.text) for ln in lines
                       if _in_margin(ln, size) and ln.text.strip() and not ln.row and not _CAPTION.match(ln.text)})
    threshold = max(3, len(pages) // 10)
    running = {k for k, n in counts.items() if n >= threshold}
    running |= {k for k in counts if _PAGE_NUMBER.match(k.replace("#", "1"))}
    return running


def _group_boards(lines: list[_Line]) -> list[_Board]:
    rows = sorted((ln for ln in lines if ln.row), key=lambda ln: (round(ln.bbox[0] / 4), ln.bbox[1]))
    groups: list[list[_Line]] = []
    for ln in rows:
        g = groups[-1] if groups else None
        if g and abs(ln.bbox[0] - g[-1].bbox[0]) < 4:
            height = g[-1].bbox[3] - g[-1].bbox[1]
            if 0 < ln.bbox[1] - g[-1].bbox[1] < 1.6 * height:
                g.append(ln)
                continue
        groups.append([ln])
    boards = []
    for g in groups:
        for i in range(0, len(g) - 7, 8):
            rows8 = g[i:i + 8]
            x0 = min(r.squares[0] for r in rows8)
            x1 = max(r.squares[2] for r in rows8)
            box = (x0, rows8[0].squares[1], x1, rows8[-1].squares[3])
            boards.append(_Board(rows8, box, placement([r.row for r in rows8])))
    return boards


def _diagram_labels(bboxes: list[tuple], lines: list[_Line], ocr: bool = False) -> list[str | None]:
    """The number printed beside, above or below each diagram, if any."""
    # Rank coordinates ("8" … "1") are stacks of one-digit lines at the same x: never labels.
    columns = Counter(round(ln.bbox[0] / 3) for ln in lines if len(ln.text.strip()) == 1)
    candidates = []
    for ln in lines:
        m = _LABEL.match(ln.text)
        if not m or ln.row or (len(ln.text.strip()) == 1 and columns[round(ln.bbox[0] / 3)] >= 4):
            continue
        if any(t.kind == "move" for t in tokenize(ln.text, ocr)):
            continue
        group = "captioned" if m["captioned"] else "number"
        number = m[group].replace(" ", "")
        # OCR may join the captions of boards printed side by side: "122) White to play 125) White to play".
        more = list(_LABEL_MORE.finditer(ln.text, m.end()))
        if not more:
            candidates.append((ln.bbox, number))
            continue
        starts = [m.start(group)] + [x.start(1) for x in more] + [len(ln.text)]
        for label, a, b in zip([number] + [x[1] for x in more], starts, starts[1:]):
            box = _span_bbox(ln.boxes, a, b)
            if box:
                candidates.append((box, label))
    pairs = []
    for i, (x0, y0, x1, y1) in enumerate(bboxes):
        square = (x1 - x0) / 8
        for j, ((lx0, ly0, lx1, ly1), label) in enumerate(candidates):
            if _rank_coordinate(label, (lx0, ly0, lx1, ly1), (x0, y0, x1, y1)):
                continue  # "8" beside the top rank: a coordinate, not the diagram's number
            overlaps = min(x1, lx1) - max(x0, lx0) > 0
            if x0 - 2.5 * square < lx1 <= x0 + 5 and ly0 < y0 + 0.4 * (y1 - y0) and ly1 > y0 - 10:
                d = x0 - lx1  # left of the board's top
            elif overlaps and ly1 <= y0 + 5 and y0 - ly1 < 40:
                d = y0 - ly1  # above
            elif overlaps and ly0 >= y1 - 5 and ly0 - y1 < 40:
                d = ly0 - y1  # below
            else:
                continue
            pairs.append((d, i, j))
    # Closest pairs first, each number used once: a board whose own caption is unreadable must not
    # take the caption of the board above it.
    labels: list[str | None] = [None] * len(bboxes)
    used = set()
    for d, i, j in sorted(pairs):
        if labels[i] is None and j not in used:
            labels[i] = candidates[j][1]
            used.add(j)
    return labels


def _rank_coordinate(label: str, box, board) -> bool:
    """True for a digit printed beside a board that names the rank it is level with."""
    x0, y0, x1, y1 = board
    square = (x1 - x0) / 8
    lx0, ly0, lx1, ly1 = box
    if not (len(label) == 1 and label in "12345678" and x0 - square < lx1 <= x0 + 5):
        return False
    row = int(((ly0 + ly1) / 2 - y0) // square)
    return 0 <= row < 8 and int(label) in (8 - row, row + 1)  # either way up


def _page_blocks(n: int, lines: list[_Line], images: list[_ImageBoard], body: float, page_size,
                 ocr: bool = False) -> list[Block]:
    boards = _group_boards(lines)
    board_labels = dict(zip(map(id, boards), _diagram_labels([b.bbox for b in boards], lines, ocr)))
    image_labels = dict(zip(map(id, images), _diagram_labels([i.bbox for i in images], lines, ocr)))
    board_of = {id(r): b for b in boards for r in b.rows}
    # Borders and coordinates printed around a board.
    zones = [(b[0] - 25, b[1] - 25, b[2] + 25, b[3] + 25) for b in [x.bbox for x in boards] + [i.bbox for i in images]]
    pending_images = list(images)

    def image_block(img: _ImageBoard) -> Block:
        b = img.board
        caption_turn, task, points = _caption(img.bbox, lines)
        block = _diagram_block(n, img.bbox, b.placement, image_labels[id(img)],
                               confidence=b.confidence, uncertain=b.uncertain, turn=b.turn or caption_turn)
        block.alternatives, block.task, block.points = b.alternatives, task, points
        return block
    out: list[Block] = []
    current: list[_Line] = []
    last_bottom: float | None = None

    def emit_text():
        nonlocal current, last_bottom
        if not current:
            return
        block = _text_block(n, current)
        top = current[0].bbox[1]
        left, right = block.source.bbox[0], block.source.bbox[2]
        # A diagram goes before the first text of its own column that is printed below it.
        for img in [i for i in pending_images if i.bbox[1] < top and min(right, i.bbox[2]) > max(left, i.bbox[0])]:
            pending_images.remove(img)
            out.append(image_block(img))
            last_bottom = None
        if _heading(current, body):
            block.kind = "heading"
            block.game_header = bool(GAME_HEADER.match(block.text))
        elif last_bottom is not None and 0 <= top - last_bottom < 2.2 * max(current[0].size, 1):
            block.flow_break = False
        elif last_bottom is not None and top < last_bottom:  # next column
            block.flow_break = False
        elif not out and n > 0:  # first block of a page continues the previous page
            block.flow_break = False
        out.append(block)
        last_bottom = current[-1].bbox[3] if block.kind != "heading" else None
        current = []

    emitted = set()
    for ln in lines:
        board = board_of.get(id(ln))
        if board is not None:
            if id(board) not in emitted:
                emit_text()
                emitted.add(id(board))
                caption_turn, task, points = _caption(board.bbox, lines)
                block = _diagram_block(n, board.bbox, board.placement, board_labels[id(board)],
                                       turn=_marker_turn(board.bbox, lines) or caption_turn)
                block.task, block.points = task, points
                out.append(block)
                last_bottom = None
            continue
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if len(ln.text.strip()) <= 3 and any(z[0] < cx < z[2] and z[1] < cy < z[3] for z in zones):
            continue
        if current and (ln.block != current[-1].block or _game_header_line(ln.text)):
            emit_text()
        current.append(ln)
        if _game_header_line(ln.text):
            emit_text()
    emit_text()
    out.extend(image_block(img) for img in pending_images)
    return out


_TURN_CAPTION = re.compile(
    r"\b(?:(white|black|blancas|negras)\b[^.\n]{0,12}\b(?:to\s+(?:play|move)|juegan|mueven|play)"
    r"|(?:juegan|mueven)\s+(?:las\s+)?(blancas|negras))",
    re.IGNORECASE,
)


# A caption that sets a task, besides "White to play": "Ejercicio", "Test 3", "¿Es tablas?".
_TASK = re.compile(r"\b(?:ejercicio|exercise|test|puzzle)\b|¿", re.IGNORECASE)
_POINTS = re.compile(r"(\d{1,2})\s*(?:points?|puntos?)\b", re.IGNORECASE)


def _caption(bbox, lines: list[_Line]) -> tuple[str | None, bool, int | None]:
    """What the caption just above or below a diagram says: side to move, whether it is a task, points."""
    x0, y0, x1, y1 = bbox
    turn, task, points = None, False, None
    for ln in lines:
        lx0, ly0, lx1, ly1 = ln.bbox
        if min(x1, lx1) - max(x0, lx0) <= 0:
            continue
        d = ly0 - y1 if ly0 >= y1 - 5 else (y0 - ly1 if ly1 <= y0 + 5 else None)
        if d is None or d > 45:
            continue
        m = _TURN_CAPTION.search(ln.text)
        if m and (turn is None or d < turn[0]):
            side = (m[1] or m[2]).lower()
            turn = (d, "w" if side in ("white", "blancas") else "b")
        question = ln.text.rstrip().endswith("?") and not any(t.kind == "move" for t in tokenize(ln.text))
        if m or _TASK.search(ln.text) or question:
            task = True
        if p := _POINTS.search(ln.text):
            points = int(p[1])
    return (turn[1] if turn else None), task, points


def _marker_turn(bbox, lines: list[_Line]) -> str | None:
    """Side to move from a lone symbol beside a typed board (a triangle at the top or bottom)."""
    x0, y0, x1, y1 = bbox
    s = (x1 - x0) / 8
    marks = []
    for ln in lines:
        if ln.text.strip() not in ("•", "▲", "△", "▼", "▽", "■", "□"):
            continue
        cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
        if y0 <= cy <= y1 and (x1 < cx < x1 + 1.8 * s or x0 - 1.8 * s < cx < x0):
            marks.append(cy)
    if len(marks) != 1:
        return None
    return "b" if marks[0] < (y0 + y1) / 2 else "w"


def _game_header_line(text: str) -> bool:
    return len(text) < 100 and bool(GAME_HEADER.match(text)) and not any(t.kind == "move" for t in tokenize(text))


def _heading(lines: list[_Line], body: float) -> bool:
    text = " ".join(ln.text for ln in lines).strip()
    if not text or len(text) > 100 or any(t.kind == "move" for t in tokenize(text)):
        return False
    if len(lines) == 1 and _game_header_line(text):
        return True
    return len(lines) <= 2 and all(ln.size >= 1.25 * body for ln in lines)


def _text_block(page: int, lines: list[_Line]) -> Block:
    text, bold, boxes = "", [], array("f")
    for i, ln in enumerate(lines):
        if i:
            text += "\n"
            boxes.extend(_NO_BOX)
        bold.extend((a + len(text), b + len(text)) for a, b in ln.bold)
        text += ln.text
        boxes.extend(ln.boxes)
    x0 = min(ln.bbox[0] for ln in lines)
    x1 = max(ln.bbox[2] for ln in lines)
    return Block("para", text, bold, PdfSource(page, boxes, (x0, lines[0].bbox[1], x1, lines[-1].bbox[3])))


def _diagram_block(page: int, bbox, fen_placement: str | None, label: str | None, *, confidence: float = 1.0,
                   uncertain: list[int] | None = None, turn: str | None = None) -> Block:
    source = PdfSource(page, bbox=tuple(round(v, 1) for v in bbox))
    return Block("diagram", source=source, placement=fen_placement, label=label, key=f"p{page}:{bbox[0]:.0f},{bbox[1]:.0f}",
                 confidence=confidence, uncertain=uncertain or [], turn=turn)


def _span_bbox(boxes: array, start: int, end: int) -> tuple[float, float, float, float] | None:
    """The box around the characters text[start:end] of a line."""
    chars = [boxes[4 * i:4 * i + 4] for i in range(start, end)]
    chars = [c for c in chars if not math.isnan(c[0]) and c[2] > c[0]]
    if not chars:
        return None
    return (min(c[0] for c in chars), min(c[1] for c in chars), max(c[2] for c in chars), max(c[3] for c in chars))


def _rects(boxes: array, start: int, end: int) -> list[list[float]]:
    """Character boxes of text[start:end], merged into one rectangle per line."""
    rects: list[list[float]] = []
    for i in range(start, end):
        x0, y0, x1, y1 = boxes[4 * i:4 * i + 4]
        if math.isnan(x0) or x1 <= x0:
            continue
        r = rects[-1] if rects else None
        if r and abs(y0 - r[1]) < 0.5 * (y1 - y0) and x0 >= r[0] - 1:
            r[2], r[3] = max(r[2], x1), max(r[3], y1)
            r[1] = min(r[1], y0)
        else:
            rects.append([x0, y0, x1, y1])
    return [[round(v, 1) for v in r] for r in rects]
