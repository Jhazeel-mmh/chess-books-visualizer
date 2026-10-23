"""Reading figurines by their shape: the nearest labelled shapes vote; a letter is not a figurine."""

import numpy as np
import chess

from cbv.vision.figurines import SIZE, FigurineReader, _patch


def shape(seed: int, noise: float = 0.0, rng=None) -> np.ndarray:
    base = np.random.default_rng(seed).normal(size=SIZE * SIZE)
    if noise:
        base = base + rng.normal(scale=noise, size=base.size)
    return ((base - base.mean()) / base.std()).astype(np.float32)


def test_a_figurine_is_read_by_the_shapes_nearest_to_it():
    rng = np.random.default_rng(0)
    pieces = [chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING]
    shapes = np.stack([shape(p, 0.3, rng) for p in pieces for _ in range(6)])
    labels = np.array([p for p in pieces for _ in range(6)])
    reader = FigurineReader(shapes, labels)
    assert reader.read(shape(chess.ROOK, 0.3, rng)) == (chess.ROOK, True)
    assert reader.read(shape(99)) is None  # unlike any figurine: no hint


def test_a_patch_is_the_ink_scaled_to_a_square():
    page = np.ones((200, 200), np.float32)
    page[50:90, 60:80] = 0  # a dark bar, at zoom 5: points (12, 10)–(16, 18)
    v = _patch(page, (10, 8, 20, 20))
    assert v.shape == (SIZE * SIZE,) and abs(float(v.mean())) < 1e-4
    assert _patch(np.ones((50, 50), np.float32), (0, 0, 5, 5)) is None  # no ink
