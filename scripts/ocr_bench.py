"""How well scanned books are read, measured where the truth is known.

A clean digital book is parsed as it is (its links are the truth), then its text is damaged the way
an OCR text layer damages a chess book (figurines as junk spellings, c read as e, 5 as S, move
numbers split, moves glued or garbled) and parsed again as a scan. Every move linked from the
damaged text is checked against the move linked at the same place in the clean text.

    python scripts/ocr_bench.py [book file] [--seed N]

The default book is the library's clean EPUB. Nothing is written.
"""

from __future__ import annotations

import copy
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from cbv import ingest  # noqa: E402
from cbv.notation.tokenizer import tokenize  # noqa: E402
from cbv.parse import analyze  # noqa: E402

LIBRARY = Path("~/.local/share/chess-books-visualizer/books").expanduser()
DEFAULT = LIBRARY / "667ae76200f72d8304d3a14fcb5a92c27241a0c4" / "book.epub"

# How a scan of *Mi sistema* spells each figurine (a few of the commonest per piece).
SPELLINGS = {
    "N": ["tLl", "ltJ", "4J", "T", "lLl", "ttJ", "tD", "CtJ", "ttl", "lD"],
    "B": ["i", ".i", "i.", "/", "J.", "fJ."],
    "R": ["!", ":g", "E:", "l'!", "B:", "E!", "13"],
    "Q": ["'lW", "W", "V;Y", "'eN", "\\W", "Wf"],
    "K": ["cj;>", "'it>", "i>", "<j;>", "c;t>", "@"],
}
FILES = {"c": "e", "e": "c", "b": "h", "h": "b"}
RANKS = {"5": "S", "1": "l", "8": "B", "6": "G"}


class Damage:
    """The OCR damage, at rates seen in real scans."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.style: dict[str, str] = {}

    def page(self) -> None:
        """A new page: each piece gets the spelling this page mostly uses."""
        self.style = {p: self.rng.choice(s) for p, s in SPELLINGS.items()}

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    def piece(self, letter: str) -> str:
        return self.style[letter] if self.chance(0.7) else self.rng.choice(SPELLINGS[letter])

    def move(self, text: str) -> str:
        if self.chance(0.02):
            return self.rng.choice(["lDo", "tLlt", "ltln", "{cJ", "2Ui?"])  # unreadable
        out = []
        for i, c in enumerate(text):
            if c in "KQRBN" and i == 0:
                out.append(self.piece(c))
            elif c in FILES and self.chance(0.03):
                out.append(FILES[c])
            elif c in RANKS and self.chance(0.06 if c == "5" else 0.03):
                out.append(RANKS[c])
            elif c == "+" and self.chance(0.08):
                continue
            elif c == "x" and self.chance(0.04):
                continue
            else:
                out.append(c)
        moved = "".join(out)
        if len(moved) == 2 and moved[0] in "abcdefgh" and self.chance(0.03):
            moved = moved[0] + " " + moved[1]  # "d 5"
        return moved

    def number(self, text: str) -> str:
        digits = "".join(c for c in text if c.isdigit())
        rest = text[len(digits):] if text.startswith(digits) else text.replace(digits, "", 1)
        if len(digits) == 2 and self.chance(0.15):
            digits = digits[0] + " " + digits[1]  # "1 1."
        if self.chance(0.05):
            digits = digits.replace("1", "l")
        if rest == "." and self.chance(0.03):
            rest = "J"  # the dot read as J, glued to the move
        return digits + rest


def damaged(doc, seed: int):
    """A scan-like copy of the document, and per block the clean end of each damaged move."""
    rng = random.Random(seed)
    damage = Damage(rng)
    noisy = copy.deepcopy(doc)
    where: dict[tuple[int, int], int] = {}
    for i, block in enumerate(noisy.blocks):
        if i % 12 == 0:
            damage.page()
        if block.kind == "diagram":
            continue
        text, pos, out = block.text, 0, []
        for t in tokenize(text):
            out.append(text[pos:t.start])
            if t.kind == "move":
                out.append(damage.move(t.text))
                where[(i, len("".join(out)))] = t.end
            elif t.kind == "number":
                out.append(damage.number(t.text))
            else:
                out.append(t.text)
            pos = t.end
        out.append(text[pos:])
        block.text = "".join(out)
        block.bold = []
        block.ocr = True
        block.fixes = []
    return noisy, where


def bench(path: Path, seed: int) -> None:
    t0 = time.perf_counter()
    book = ingest.open_book(path, cache=path.with_name("vision.json"), read_only=True)
    clean = analyze(book.doc)
    truth = {(r.block, r.end): n.fen.split()[:2] for g in clean.anchored.games for n in g.nodes() for r in n.refs}
    noisy_doc, where = damaged(book.doc, seed)
    noisy = analyze(noisy_doc)
    right = wrong = extra = right_guessed = wrong_guessed = 0
    for game in noisy.anchored.games:
        for node in game.nodes():
            for ref in node.refs:
                clean_end = where.get((ref.block, ref.end))
                expected = truth.get((ref.block, clean_end)) if clean_end is not None else None
                if expected is None:
                    extra += 1
                elif node.fen.split()[:2] == expected:
                    right += 1
                    right_guessed += ref in node.guessed
                else:
                    wrong += 1
                    wrong_guessed += ref in node.guessed
    linked = right + wrong
    print(f"{path.name} (seed {seed}, {time.perf_counter() - t0:.0f}s)")
    print(f"  clean: {len(truth)} moves linked")
    print(f"  damaged: {noisy.anchored.moves_resolved} linked; checked against the clean text: {linked}"
          f" ({extra} where the clean text has none)")
    print(f"  recall {100 * right / len(truth):.1f}%   precision {100 * right / max(1, linked):.1f}%"
          f"   (shown as uncertain: {right_guessed} right, {wrong_guessed} wrong)")


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book", type=Path, nargs="?", default=DEFAULT)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    bench(args.book, args.seed)
