from cbv.ingest.chessfonts import GlyphMapper, decode_row, placement


def test_marroquin_rows_with_border_and_rank_labels():
    # Woodpecker Method, puzzle 49 (Chess Merida, symbol-encoded at U+F0xx).
    raw = [
        " ",
        "  ",
        "   ",
        "  ",
        "    ",
        "   ",
        "   ",
        "    ",
    ]
    rows = [decode_row(r) for r in raw]
    assert all(r and r.table == "marroquin" for r in rows)
    assert placement(rows) == "r3r1k1/3b2pp/2p5/p1RpPp2/3Q1P2/1q2P1P1/6BP/R5K1"


def test_border_rows_are_not_squares():
    assert decode_row("" + "" * 8 + "") is None


def test_skak_rows():
    # Polgar 5334, problem 1699 (LaTeX skak font).
    rows = [decode_row(r) for r in ["0ZQZ0Z0Z", "Z0J0Z0Z0", "0Z0Z0Z0Z", "Z0Z0Z0Z0",
                                    "0Z0Z0Z0Z", "Z0Z0Zno0", "0Z0ZRZRZ", "Z0Z0ZkZ0"]]
    assert placement(rows) == "2Q5/2K5/8/8/8/5np1/4R1R1/5k2"


def test_rows_with_wrong_square_colours_are_rejected():
    rows = [decode_row("0ZQZ0Z0Z")] * 8  # every row starting on a light square
    assert placement(rows) is None


def test_figurine_font_text():
    m = GlyphMapper()
    assert m.figurine_text("NXe4+") == "♘xe4+"
    a = m.figurine_text("¥b5")
    assert a[0] != "¥" and a[1:] == "b5" and m.figurine_text("¥") == a[0]
