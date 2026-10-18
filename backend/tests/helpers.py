"""Builds tiny DocStreams for tests: '**...**' marks bold text, '# ' a heading."""

from __future__ import annotations

import re

from cbv.ingest.model import Block, DocStream


def block(markup: str) -> Block:
    kind = "para"
    if markup.startswith("# "):
        kind, markup = "heading", markup[2:]
    text, bold, pos = "", [], 0
    for m in re.finditer(r"\*\*(.+?)\*\*", markup):
        text += markup[pos:m.start()]
        bold.append((len(text), len(text) + len(m[1])))
        text += m[1]
        pos = m.end()
    text += markup[pos:]
    return Block(kind, text, bold)


def cont(markup: str) -> Block:
    """A block whose text runs on from the previous one (like a PDF line)."""
    b = block(markup)
    b.flow_break = False
    return b


def header(title: str) -> Block:
    return Block("heading", title, game_header=True)


def diagram(placement: str | None, label: str | None = None) -> Block:
    return Block("diagram", placement=placement, label=label)


def doc(*paragraphs: str | Block) -> DocStream:
    return DocStream([p if isinstance(p, Block) else block(p) for p in paragraphs])
