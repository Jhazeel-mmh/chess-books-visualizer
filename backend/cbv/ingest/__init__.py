"""Reads book files into a :class:`~cbv.ingest.model.DocStream`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .model import DocStream, Mark

SUPPORTED = {".epub", ".pdf"}


class UnsupportedFormat(Exception):
    pass


class Book(Protocol):
    format: str
    doc: DocStream

    def export(self, out: Path, marks: list[Mark]) -> dict:
        """Writes what the reader needs to show the marks, and returns the layout description."""
        ...


Progress = Callable[[float], None]


def open_book(path: Path, cache: Path | None = None, progress: Progress | None = None) -> Book:
    """Reads a book.

    ``cache`` is a file where diagrams read from images are kept between runs;
    ``progress`` is called with the fraction of the book read so far.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from .pdf import PdfBook

        return PdfBook(path, cache, progress)
    if suffix == ".epub":
        from .epub import EpubBook

        return EpubBook(path, cache, progress)
    raise UnsupportedFormat(suffix)


def load(path: Path) -> DocStream:
    return open_book(path).doc
