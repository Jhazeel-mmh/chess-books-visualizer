"""Square classifiers: small CNNs (trained by ``tools/vision_train.py``) run with OpenCV.

Two networks ship with the app. ``pieces.onnx`` was trained on pieces alone; ``pieces-marks.onnx``
also saw the marks books print on empty squares (asterisks, digits, dots). Neither is better on
every book: the reader picks, per book, the one that reads its squares with more certainty.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

CLASSES = ".PNBRQKpnbrqk"  # index = class id; "." is an empty square
WEIGHTS = Path(__file__).with_name("pieces.onnx")
MODELS = [WEIGHTS, Path(__file__).with_name("pieces-marks.onnx")]
_lock = threading.Lock()  # an OpenCV network runs one batch at a time


def available() -> list[int]:
    """Indexes in MODELS of the networks that are installed (the first one always is)."""
    return [i for i, path in enumerate(MODELS) if path.exists()]


@lru_cache(maxsize=None)
def _net(model: int) -> cv2.dnn.Net:
    return cv2.dnn.readNetFromONNX(str(MODELS[model]))


def probabilities(cells: np.ndarray, batch: int = 512, model: int = 0) -> np.ndarray:
    """Class probabilities for squares of shape (N, 32, 32), values 0 (ink) .. 1 (paper)."""
    if len(cells) == 0:
        return np.zeros((0, len(CLASSES)), np.float32)
    out = []
    with _lock:
        net = _net(model)
        for i in range(0, len(cells), batch):
            net.setInput(np.ascontiguousarray(cells[i:i + batch, None], np.float32))
            out.append(net.forward().copy())
    return np.concatenate(out)
