import numpy as np
import pytest

from cbv.vision.board import find_boards
from cbv.vision.classify import CLASSES, WEIGHTS
from cbv.vision.recognize import decide, placement, read_boards, turn_marker


def drawn_board(cell=30, marker=None):
    """A framed board with gray dark squares and a black blob on e4, on a page with margins."""
    size = 8 * cell
    img = np.full((size + 120, size + 160), 255, np.uint8)
    x0, y0 = 80, 60
    img[y0 - 3:y0 + size + 3, x0 - 3:x0 + size + 3] = 0  # frame
    for r in range(8):
        for c in range(8):
            img[y0 + r * cell:y0 + (r + 1) * cell, x0 + c * cell:x0 + (c + 1) * cell] = 255 if (r + c) % 2 == 0 else 170
    r, c = 4, 4  # e4
    img[y0 + r * cell + 8:y0 + (r + 1) * cell - 8, x0 + c * cell + 8:x0 + (c + 1) * cell - 8] = 0
    if marker == "black-top":
        img[y0 + 10:y0 + 25, x0 - 40:x0 - 25] = 0
    return img, (x0, y0, x0 + size, y0 + size)


def test_finds_a_framed_board_and_its_inner_edge():
    img, (x0, y0, x1, y1) = drawn_board()
    boards = find_boards(img)
    assert len(boards) == 1
    bx0, by0, bx1, by1 = boards[0].box
    assert abs(bx0 - x0) <= 2 and abs(by0 - y0) <= 2 and abs(bx1 - x1) <= 2 and abs(by1 - y1) <= 2
    cells = boards[0].cells
    assert cells.shape == (64, 32, 32)
    assert cells[36].mean() < cells[34].mean()  # e4 holds ink, c4 (also a light square) is empty


def test_text_and_lines_are_not_boards():
    img = np.full((400, 400), 255, np.uint8)
    img[100:102, 20:380] = 0  # a horizontal rule
    img[200:260, 50:110] = 0  # a black box with no squares inside
    assert find_boards(img) == []


def test_turn_marker_beside_the_board():
    img, box = drawn_board(marker="black-top")
    assert turn_marker(img, box) == "b"
    img, box = drawn_board()
    assert turn_marker(img, box) is None


def one_hot(labels):
    p = np.full((64, len(CLASSES)), 0.001)
    for i, label in enumerate(labels):
        p[i, CLASSES.index(label)] = 0.9
    return p


def test_one_king_per_side_and_no_pawns_on_the_edge_ranks():
    labels = ["."] * 64
    labels[60] = "K"  # e1
    labels[4] = "k"  # e8
    labels[5] = "K"  # a second white king on f8 (misread)
    labels[1] = "P"  # a pawn on b8 (impossible)
    p = one_hot(labels)
    p[60, CLASSES.index("K")] = 0.95  # the real king is the more certain one
    p[5, CLASSES.index("Q")] = 0.5  # the misread king's second choice
    p[1, CLASSES.index("N")] = 0.3
    decided, certainty = decide(p)
    assert placement(decided) == "1N2kQ2/8/8/8/8/8/8/4K3"
    assert certainty.shape == (64,)


def test_a_second_king_the_classifier_is_sure_of_stays():
    # "The black king on b2 or on h2": books do print two kings of one colour.
    labels = ["."] * 64
    labels[60], labels[4], labels[49], labels[55] = "K", "k", "k", "k"
    decided, _ = decide(one_hot(labels))
    assert placement(decided) == "4k3/8/8/8/8/8/1k5k/4K3"


@pytest.mark.skipif(not WEIGHTS.exists(), reason="classifier weights not trained")
def test_reads_an_empty_board_as_empty():
    img, _ = drawn_board()
    img[60 + 4 * 30 + 8:60 + 5 * 30 - 8, 80 + 4 * 30 + 8:80 + 5 * 30 - 8] = 255  # remove the blob
    boards = read_boards(img)
    assert len(boards) == 1 and boards[0].placement == "8/8/8/8/8/8/8/8"


def test_a_book_is_read_with_the_network_that_is_surer_of_it(monkeypatch):
    from cbv.vision import recognize
    from cbv.vision.recognize import ReadBoard, choose_network

    labels = ["."] * 64
    labels[4], labels[60], labels[59] = "k", "K", "Q"
    sure = one_hot(labels)
    unsure = sure.copy()
    unsure[59] = 0.0
    unsure[59, CLASSES.index("Q")], unsure[59, CLASSES.index("q")] = 0.5, 0.5  # white or black queen?
    boards = [ReadBoard(box=(0, 0, 8, 8), placement="", confidence=0.0, cells=np.zeros((64, 32, 32), np.float32), probs=unsure)
              for _ in range(3)]
    monkeypatch.setattr(recognize, "available", lambda: [0, 1])
    monkeypatch.setattr(recognize, "probabilities", lambda cells, model=0: np.concatenate([sure] * 3))
    assert choose_network(boards) == 1
    assert boards[0].placement == "4k3/8/8/8/8/8/8/3QK3" and boards[0].uncertain == []
