"""EPUB books: chapters in spine order, one block per paragraph.

Each block remembers which XHTML text nodes its characters came from, so the
moves the parser finds can be wrapped in ``<span>`` elements and the chapter
served back to the reader with clickable moves.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import cv2
import numpy as np
import pymupdf
from lxml import etree

from ..notation.pieces import GLYPH_FIRST
from .model import Block, DocStream, Mark
from .pdf import GAME_HEADER

XHTML = "http://www.w3.org/1999/xhtml"
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = _HEADINGS | {"p", "li", "dd", "dt", "td", "th", "caption", "figcaption", "pre", "div", "blockquote", "section"}
_BOLD_TAGS = {"b", "strong"}
_BOLD_DECL = re.compile(r"font-weight\s*:\s*(bold|bolder|[6-9]00)", re.IGNORECASE)
_CLASS_SELECTOR = re.compile(r"^\s*[\w-]*\.([\w-]+)\s*$")
_PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True)


@dataclass
class _Segment:
    start: int
    end: int
    node: etree._Element | None  # None for characters the parser added (line breaks, image glyphs)
    attr: str  # "text" or "tail"


@dataclass
class EpubSource:
    chapter: int
    element: etree._Element
    segments: list[_Segment] = field(default_factory=list)


class EpubBook:
    format = "epub"

    def __init__(self, path: Path, cache: Path | None = None, progress=None, read_only: bool = False):
        from ..vision.recognize import BoardCache

        self.path = path
        self._boards = BoardCache(cache, read_only)
        with zipfile.ZipFile(path) as z:
            self.names = set(z.namelist())
            opf_path = _rootfile(z)
            opf = etree.fromstring(z.read(opf_path), _PARSER)
            base = posixpath.dirname(opf_path)
            manifest = {
                item.get("id"): (posixpath.normpath(posixpath.join(base, unquote(item.get("href", "")))), item.get("media-type", ""))
                for item in opf.iter("{*}item")
            }
            self.chapters = [
                manifest[ref.get("idref")][0]
                for ref in opf.iter("{*}itemref")
                if ref.get("idref") in manifest and "html" in manifest[ref.get("idref")][1]
            ]
            bold_classes = set()
            for href, media in manifest.values():
                if media == "text/css" and href in self.names:
                    bold_classes |= _bold_classes(z.read(href).decode("utf-8", "replace"))
            self.trees = [etree.fromstring(z.read(c), _PARSER) if c in self.names else None for c in self.chapters]
            images = {n: z.read(n) for n in self.names if n.lower().endswith((".gif", ".png", ".jpg", ".jpeg"))}

        self._glyphs: dict[str, str] = {}
        self._read_boards: list[tuple[Block, object]] = []
        blocks: list[Block] = []
        for ci, (href, tree) in enumerate(zip(self.chapters, self.trees)):
            if progress:
                progress(ci / max(1, len(self.chapters)))
            if tree is None:
                continue
            body = next(tree.iter("{*}body"), tree)
            for el in _block_elements(body):
                block = self._block(ci, href, el, bold_classes, images)
                if block is not None:
                    blocks.append(block)
        self.doc = DocStream(blocks, self._sections(blocks))
        self._boards.save()  # after the book-level choice of network
        for block, board in self._read_boards:
            block.placement, block.confidence, block.uncertain = board.placement, board.confidence, board.uncertain
            block.turn, block.alternatives = board.turn, board.alternatives

    def _sections(self, blocks: list[Block]) -> list[tuple[int, str]]:
        """Each chapter's title, from its first block."""
        sections, seen = [], set()
        for i, block in enumerate(blocks):
            chapter = block.source.chapter
            if chapter not in seen:
                seen.add(chapter)
                title = _chapter_title(self.trees[chapter])
                if title:
                    sections.append((i, title))
        return sections

    def export(self, out: Path, marks: list[Mark]) -> dict:
        """Writes the chapters with marks wrapped in spans under ``out/epub/`` and returns the layout."""
        wraps: dict[tuple[int, str], list[tuple[int, int, Mark]]] = {}
        nodes: dict[int, etree._Element] = {}
        for mark in marks:
            block = self.doc.blocks[mark.ref.block]
            src: EpubSource = block.source
            if mark.kind == "diagram":
                src.element.set("data-cbv-diagram", mark.id)
                src.element.set("class", (src.element.get("class", "") + " cbv-diagram").strip())
                continue
            for seg in src.segments:
                a, b = max(mark.ref.start, seg.start), min(mark.ref.end, seg.end)
                if seg.node is None or a >= b:
                    continue
                nodes[id(seg.node)] = seg.node
                wraps.setdefault((id(seg.node), seg.attr), []).append((a - seg.start, b - seg.start, mark))
        for (node_id, attr), items in wraps.items():
            node = nodes[node_id]
            for a, b, mark in sorted(items, key=lambda w: -w[0]):
                _wrap(node, attr, a, b, mark)

        root = out / "epub"
        for href, tree in zip(self.chapters, self.trees):
            if tree is None:
                continue
            for bad in list(tree.iter("{*}script")):
                bad.getparent().remove(bad)
            target = (root / href).resolve()
            if root.resolve() not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(etree.tostring(tree, xml_declaration=True, encoding="utf-8"))
        return {
            "kind": "epub",
            "chapters": [{"href": href, "title": _chapter_title(tree)} for href, tree in zip(self.chapters, self.trees)],
            "blocks": [b.source.chapter for b in self.doc.blocks],
        }

    def _block(self, chapter: int, href: str, el, bold_classes: set[str], images: dict[str, bytes]) -> Block | None:
        name = etree.QName(el).localname
        if not "".join(el.itertext()).strip():
            # No text: a diagram if one of its images shows a board, otherwise nothing to read.
            for img in el.iter("{*}img", "{*}image"):
                src = img.get("src") or img.get("{http://www.w3.org/1999/xlink}href") or ""
                path = posixpath.normpath(posixpath.join(posixpath.dirname(href), unquote(src)))
                found = self._boards.read(path, lambda path=path: _read_image(images.get(path)))
                board = found[0] if found else None
                if board is not None:
                    block = Block("diagram", source=EpubSource(chapter, img), key=f"{href}#{path}")
                    self._read_boards.append((block, board))  # filled in once the whole book is read
                    return block
            return None
        text, segments, bold = self._collect(el, bold_classes, href)
        src = EpubSource(chapter, el, segments)
        if name in _HEADINGS:
            title = " ".join(text.split())
            return Block("heading", text, bold, src, game_header=bool(GAME_HEADER.search(title)))
        return Block("para", text, bold, src)

    def _collect(self, el, bold_classes: set[str], href: str):
        text: list[str] = []
        segments: list[_Segment] = []
        bold: list[tuple[int, int]] = []
        pos = 0

        def add(node, attr: str, s: str, is_bold: bool):
            nonlocal pos
            if not s:
                return
            segments.append(_Segment(pos, pos + len(s), node, attr))
            if is_bold:
                bold.append((pos, pos + len(s)))
            text.append(s)
            pos += len(s)

        def walk(node, inherited: bool):
            if not isinstance(node.tag, str):  # comments, processing instructions
                return
            local = etree.QName(node).localname
            b = inherited or _is_bold(node, local, bold_classes)
            if local == "br":
                add(None, "text", "\n", b)
            elif local in ("img", "image"):
                # An inline image in text is usually a figurine: a glyph the parser resolves.
                src = node.get("src") or node.get("{http://www.w3.org/1999/xlink}href") or ""
                key = posixpath.normpath(posixpath.join(posixpath.dirname(href), unquote(src)))
                glyph = self._glyphs.setdefault(key, chr(GLYPH_FIRST + 0x800 + len(self._glyphs)))
                add(None, "text", glyph, b)
            elif local in ("script", "style"):
                return
            add(node, "text", node.text, b)
            for child in node:
                walk(child, b)
                add(child, "tail", child.tail, b)

        walk(el, False)
        return "".join(text), segments, bold


def _rootfile(z: zipfile.ZipFile) -> str:
    container = etree.fromstring(z.read("META-INF/container.xml"), _PARSER)
    return next(container.iter("{*}rootfile")).get("full-path")


def _bold_classes(css: str) -> set[str]:
    found = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if _BOLD_DECL.search(body):
            for sel in selectors.split(","):
                m = _CLASS_SELECTOR.match(sel)
                if m:
                    found.add(m[1])
    return found


def _is_bold(node, local: str, bold_classes: set[str]) -> bool:
    if local in _BOLD_TAGS or _BOLD_DECL.search(node.get("style", "")):
        return True
    return any(c in bold_classes for c in node.get("class", "").split())


def _block_elements(root):
    """Leaf block elements in document order (blocks that contain no other blocks)."""
    for el in root.iterchildren():
        if not isinstance(el.tag, str):
            continue
        local = etree.QName(el).localname
        has_inner = any(isinstance(d.tag, str) and etree.QName(d).localname in _BLOCKS for d in el.iterdescendants())
        if local in _BLOCKS and not has_inner:
            yield el
        elif has_inner:
            yield from _block_elements(el)
        elif local in ("img", "image", "svg"):
            yield el


def _read_image(data: bytes | None) -> list:
    """The board shown in an image file (a list of zero or one boards)."""
    from ..vision.recognize import read_boards

    if not data:
        return []
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        try:
            pix = pymupdf.Pixmap(data)
        except Exception:
            return []
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    if img.ndim == 3 and img.shape[2] == 4:  # transparent background: put it on paper
        alpha = img[:, :, 3:4].astype(np.float32) / 255
        img = (img[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    if img.ndim == 3:
        img = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGR2GRAY)
    return read_boards(img)[:1]


def _wrap(node, attr: str, a: int, b: int, mark: Mark) -> None:
    """Wraps characters [a, b) of ``node.text`` or ``node.tail`` in a span for the mark."""
    span = etree.Element(f"{{{XHTML}}}span" if node.tag.startswith(f"{{{XHTML}}}") else "span")
    span.set("class", f"cbv-{mark.kind}" + (" cbv-uncertain" if mark.uncertain else ""))
    span.set("data-cbv-" + ("node" if mark.kind == "move" else "unresolved"), mark.id)
    original = getattr(node, attr)
    span.text, span.tail = original[a:b], original[b:]
    setattr(node, attr, original[:a])
    if attr == "text":
        node.insert(0, span)
    else:
        parent = node.getparent()
        parent.insert(parent.index(node) + 1, span)


def _chapter_title(tree) -> str | None:
    if tree is None:
        return None
    for el in tree.iter():
        if isinstance(el.tag, str) and etree.QName(el).localname in _HEADINGS:
            title = " ".join("".join(el.itertext()).split())
            if title:
                return title[:80]
    return None
