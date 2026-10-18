"""Finds chess diagrams in an image and cuts them into 64 squares.

Printed diagrams almost always have a frame: long straight ink lines that
nothing else on a chess page has (hatching is diagonal, pieces and letters are
short). Each roughly square frame is shrunk to its inner edge, divided into an
8×8 grid, and kept only if the squares really alternate light and dark the way
a board does (light square at the top left).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

CELL = 32  # side of the normalized square images given to the classifier


@dataclass
class FoundBoard:
    # Inner board area (without frame) in image pixels: x0, y0, x1, y1.
    box: tuple[int, int, int, int]
    # 64 normalized squares, a8..h8, a7..h7, …, a1..h1 (as printed, top row first): float32 0 (ink) .. 1 (paper).
    cells: np.ndarray
    # How clearly the squares alternate (difference of light and dark square backgrounds, 0..1).
    contrast: float


def find_boards(gray: np.ndarray, min_size: int = 64) -> list[FoundBoard]:
    """Boards in a grayscale image (uint8, white paper), largest first."""
    if min(gray.shape) < min_size:
        return []
    ink = _ink_mask(gray)
    boxes = _frame_boxes(ink, min_size)
    found = []
    for box in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        if any(_overlap(box, f.box) > 0.3 for f in found):
            continue
        board = board_from_box(gray, box, ink)
        if board is not None:
            found.append(board)
    return found


def board_from_box(gray: np.ndarray, box: tuple[int, int, int, int], ink: np.ndarray | None = None) -> FoundBoard | None:
    """Reads a board whose outer edge (frame included) is ``box``; None if it is not a board."""
    if ink is None:
        ink = _ink_mask(gray)
    inner = _inside_frame(ink, box)
    x0, y0, x1, y1 = inner
    w, h = x1 - x0, y1 - y0
    if w < 32 or h < 32 or not 0.85 < w / h < 1.18:
        return None
    region = gray[y0:y1, x0:x1].astype(np.float32)
    # Ink level: the frame and the darkest few pixels (a sparse board may have almost no ink).
    bx0, by0, bx1, by1 = box
    outer = gray[by0:by1, bx0:bx1]
    frame = np.concatenate([outer[: y0 - by0 + 1].ravel(), outer[y1 - by0:].ravel(),
                            outer[:, : x0 - bx0 + 1].ravel(), outer[:, x1 - bx0:].ravel()])
    paper = np.percentile(region, 97)
    dark = min(np.percentile(region, 0.3), np.percentile(frame, 15) if frame.size else 255)
    if paper - dark < 40:
        return None
    norm = np.clip((region - dark) / (paper - dark), 0, 1)
    contrast = _checker_contrast(norm)
    if contrast < 0.04:
        return None
    return FoundBoard(inner, _cells(norm), contrast)


def _ink_mask(gray: np.ndarray) -> np.ndarray:
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    return ink


def _frame_boxes(ink: np.ndarray, min_size: int) -> list[tuple[int, int, int, int]]:
    """Bounding boxes of roughly square figures made of long horizontal and vertical lines."""
    length = max(20, int(min_size * 0.6))
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (length, 1)))
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, length)))
    lines = cv2.dilate(horiz | vert, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(lines, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w >= min_size and h >= min_size and 0.8 < w / h < 1.25:
            boxes.append((x, y, x + w, y + h))
    return boxes


def _inside_frame(ink: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Moves each edge of ``box`` inward past the frame line(s)."""
    x0, y0, x1, y1 = box
    reach = max(3, int(0.06 * min(x1 - x0, y1 - y0)))
    region = ink[y0:y1, x0:x1] > 0

    def edge(profile: np.ndarray) -> int:
        # The last line within reach that is mostly ink belongs to the frame.
        solid = np.nonzero(profile[:reach] > 0.6)[0]
        return int(solid[-1]) + 1 if len(solid) else 0

    rows, cols = region.mean(axis=1), region.mean(axis=0)
    top, bottom = edge(rows), edge(rows[::-1])
    left, right = edge(cols), edge(cols[::-1])
    return x0 + left, y0 + top, x1 - right, y1 - bottom


def _checker_contrast(norm: np.ndarray) -> float:
    """How clearly the squares alternate: light minus dark square background, 0 if they don't.

    The background is measured in the corners of each square (pieces stand in the
    middle). A real board follows the light/dark pattern on almost every square; a
    photo or a table may have a dark half and a light half, which is not enough.
    """
    # Shrink so each square is 12×12 pixels, then average the 2×2 corner patches of every square.
    small = cv2.resize(norm, (96, 96), interpolation=cv2.INTER_AREA).reshape(8, 12, 8, 12)
    corners = np.stack([small[:, 1:3, :, 1:3], small[:, 1:3, :, 9:11], small[:, 9:11, :, 1:3], small[:, 9:11, :, 9:11]])
    # A piece may reach into some corners of its square, rarely all four: take the lightest.
    background = corners.mean(axis=(2, 4)).max(axis=0)  # 8×8
    light = (np.add.outer(np.arange(8), np.arange(8)) % 2) == 0
    lo, hi = np.median(background[~light]), np.median(background[light])
    middle = (lo + hi) / 2
    follows = ((background > middle) == light).mean()
    return float(hi - lo) if follows >= 0.7 else 0.0


def _cells(norm: np.ndarray) -> np.ndarray:
    h, w = norm.shape
    out = np.empty((64, CELL, CELL), np.float32)
    for r in range(8):
        for c in range(8):
            cell = norm[int(h * r / 8):int(h * (r + 1) / 8), int(w * c / 8):int(w * (c + 1) / 8)]
            out[r * 8 + c] = cv2.resize(cell, (CELL, CELL), interpolation=cv2.INTER_AREA)
    return out


def _overlap(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / area if area else 0.0
