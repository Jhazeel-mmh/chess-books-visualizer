# Chess Books Visualizer

Read chess books next to a live board. The app finds the **moves** and **diagrams** in a
book (EPUB, PDF and scanned PDF; later DjVu and Kindle) and links them to positions.
Click a move in the book and the board shows that position. The comments are read in
the original book itself and are never copied out.

Everything runs locally on your computer, with no AI service and nothing sent to the cloud.
The interface is in Spanish and English.

## Two ways to use a book

- **Read:** the book next to the board, which follows the moves and diagrams you click.
  - **The board always fits:** it is never cut off by the window. Resize it from its corner or
    with − / +. Drag the divider to widen the board's side, swap the board to the other side,
    or press **F** for Focus (only the board and the moves).
  - **Fix moves** (PDF books): click a move the app couldn't read, or draw a box around one it
    didn't see, then play it on the board from the position before it. A false move can be
    removed. Fixes are kept per book; the book is read again with them, so one fix can link
    the rest of a game. Moves you fixed are outlined on the page.
  - **Explore:** move pieces from any position to try your own ideas. In a legal position the
    rules apply. On an illustration (a pawn structure, two half-boards) pieces move anywhere,
    and you can drag one off the board.
  - **Arrows and circles:** right-drag draws an arrow and right-click circles a square. They
    are kept per position, with the book.
  - **Engine** (button under the board, or key E): the evaluation and best line, from Stockfish
    running offline in the browser. The line is numbered; click a move to play the line up to it
    on the board (in Explore), then step through it with ← →. In Solve mode it opens once the
    problem is over.
- **Solve:** for tactical books and sections of exercises. The book is hidden; you play the
  move on the board.
  - **How a move is judged:** the book's moves are right, and a move the book marks with ? or ??
    is refuted with the book's line. Any mate counts. Other moves are judged by the engine: a
    move counts when it is within 0.3 pawns of the best, when both are clearly winning (+3 or
    more), or when it still mates at most one move later. So a rook on one file or the next
    counts the same. Problems whose solution the book doesn't show are judged by the engine alone.
  - **Help:** hints come in three steps (the piece, the square, the move), or you can show the
    solution.
  - **Progress:** results and times are saved per problem. *Timed cycles* run through a whole set
    against the clock, as in the Woodpecker Method, and compare each cycle with the previous one.
  - **Guess the move:** play one side of a game from the book and compare your moves with the
    game's (and with the engine's view).

## The daily trainer

*Train* (in the header, or *Train today* in the library) builds a 45–60 minute session from all
your books, following GM Noël Studer's advice
([nextlevelchess.com](https://nextlevelchess.com/mastering-chess-puzzles-comprehensive-guide-to-effective-problem-solving)):

- **Calculation:** unseen positions mixed from your tactics books, with the book and theme hidden.
  No hints, a clock. You calculate to the end, enter the whole line (with the replies you
  expect) and hand it in. Every move is checked: yours count when the book gives them or the
  engine finds them as good; the replies you expect count when the book gives them or they
  defend as well as the best defence. The grade: the whole line, the first move only, or wrong. Missed positions come back after a
  week, then a month. A *test* is six positions in 45 minutes, with the solutions at the end.
- **Endgame:** a position from an endgame book, played out against Stockfish. The engine sets
  the goal (win, or hold the draw).
- **Reading:** the next pages of a concept book, opened where you left off, with a timer.
- **Guess the move:** about ten moves of a master game, continuing where you stopped.

Difficulty starts from your rating (1600–2000) and follows your results, aiming for 60–80%
right. You pick the books each part draws from (a checkbox per book and part; until you change
one, the app picks from what each book holds). You can give one area a larger share (*Focus*),
and write down at the end how focused you were and what to work on next. Streaks and weekly scores are
shown. Everything is kept in `trainer.json` in the data folder.

A diagram counts as a problem when its caption sets a task ("White to play (3 points)",
"Juegan blancas ¿Es tablas?", "Ejercicio"), when a numbered solution refers to it, or when it
stands in a section of exercises (from the table of contents); never in a section of solutions.

## Status

| Stage | What | State |
|---|---|---|
| 1 | Moves from digital EPUB/PDF: parser, game trees, reader with board | Done |
| 2 | Diagrams → positions | Done: typed diagrams (chess fonts) read exactly, image diagrams by a local classifier, corrections in the reader |
| 3 | Scanned PDF (OCR), DjVu, Kindle, descriptive notation | Scanned PDFs with an OCR text layer: done (moves read tolerantly, see below). DjVu, Kindle, descriptive notation: planned |

## How moves are recognized

Text that looks like a move only counts as one if it is legal in a position the parser
has already built. This is how the parser:

- ignores square names in prose ("the knight on f3"),
- detects the book's notation: English `KQRBN`, Spanish `RDTAC`, Unicode figurines, or an
  unknown chess font. For an unknown font, its glyphs first stand for "any piece", and each
  move that only one piece could have played votes for what its glyph means,
- works out where each variation branches from, even without brackets. A move number gives
  the side: `3.Cf6` is White's 3rd move and `3...Cf6` (or `3..Cf6`) Black's. When the text
  goes back to an earlier move (`36.Bxc6! 36.hxg4 fxg4 37.Bxc6 … 36...Kg7`), the reply goes
  to the line still waiting for it, not to the side line just read.

Puzzle books are linked through the numbers printed next to the diagrams: a solution
headed `165. Karpov – Shirov` or `973)` starts from diagram 165 or 973.

The code lives in `backend/cbv/notation` (tokenizer and matcher) and `backend/cbv/parse`
(fragments, anchoring, game trees).

## How diagrams are read

- **Typed diagrams** (a chess font, as in most modern digital books) are decoded exactly
  from the PDF text: every glyph is a square, and the light/dark pattern picks the font family.
- **Image diagrams** (EPUB pictures, scanned books) go through `backend/cbv/vision`:
  boards are found by their frame and the light/dark pattern of the squares, each square is
  classified by a small neural network that runs locally with OpenCV (`pieces.onnx`, 1 MB),
  and the result is checked with chess rules (one king per side unless the network is sure of
  a second one, no pawns on the first or last rank). The side to move is taken from markers
  beside the board or captions such as "White to play" / "Juegan las negras", and from the
  moves themselves once the diagram is linked to them.
- **Two networks, chosen per book:** one trained on pieces alone, one that also learned the marks
  books print on empty squares (asterisks, digits, dots). Neither wins everywhere, so a book is
  read with the one that is unsure of fewer of its squares: a book prints each piece with the same
  glyph, so a network that struggles with one is unsure on page after page.
- **Checked against the solution:** doubtful squares keep their other likely readings. If the
  solution printed after a diagram can't be played from it (or a printed mate isn't mate), the
  parser tries those readings, one or two squares at a time, and keeps the only one under which
  the whole solution works. The reader says when a diagram was corrected that way.
- **Diagrams to check:** the reader can step through just the diagrams worth a look (doubtful
  readings, solutions that don't fit, corrections made from the solution), each of which can be
  fixed in its editor. `make audit BOOK=…` prints the same list for a book.
- **Corrections:** any diagram can be fixed in the reader; corrections are kept per book and
  applied every time the book is analysed again.

The classifiers were trained offline on synthetic boards (DejaVu, skak and Merida pieces on
plain, gray, hatched and dotted squares, with scan damage; for `pieces-marks.onnx` also with the
marks books print on empty squares) and on typed diagrams rendered from books whose positions are
known exactly. To rebuild them: `pip install -e "backend[train]"`, then
`make vision-data vision-train` (the marks network) or
`make vision-data vision-train MARKS=--no-marks MODEL=pieces.onnx` (the other).

## How scanned books are read

Scanned PDFs usually carry an invisible OCR text layer (or Acrobat ClearScan fonts). The app
uses that text, but OCR turns figurines into junk that differs from book to book: a knight may
come out as `lLl`, `ttJ` or `lb`, a king as `'it>`. Pages with such text are read in OCR mode:

- **Piece spellings are learned per book.** Any short junk before a square is kept as the
  move's piece. Every spelling starts as "any piece"; a move that only one piece could have
  played votes for what its spelling means. Spellings with clear votes are fixed, which makes
  more moves unambiguous, over a few rounds. Rare spellings are guessed from the learned ones
  they resemble (`Ll` like `tLl`), but a guess only decides between legal moves.
- **Look-alike characters.** Ranks read as letters are accepted (`eS` is e5, `gl` g1), as are
  move numbers like `l.`, `IO.` and `21..` (when the dots don't say whose move it is, the
  position does). When a game breaks on an illegal move, the parser tries undoing up to two
  look-alike confusions (`c`/`e`, `b`/`h`, `3`/`8`, `5`/`6`) and keeps them only if several
  more moves then become legal.
- **Puzzle numbers** are read from captions such as `123) Black to play` (also `123}`) and
  exercise numbers such as `2.05`, each caption going to its closest diagram.

On the sample library this links about 4,900 moves and 800 puzzle solutions in a scanned
puzzle book (Nunn) where about 100 moves were found before, with about 96% of the moves
printed with `+` or `#` giving check on the board. Very poor OCR (some pieces read as digits)
still leaves many moves unlinked.

## Development

Requirements: Python 3.11+, Node 20+ and pnpm.

```sh
make setup   # create backend/.venv and install the frontend packages
make dev     # backend on :8000 and frontend on :5173, then open http://localhost:5173
make test    # backend tests, frontend lint, unit tests and build
make report BOOK=samples/some-book.epub   # parser accuracy for one book
make audit BOOK=samples/some-book.pdf     # diagrams read, and the ones worth checking
```

Imported books and the analysis results are stored in `~/.local/share/chess-books-visualizer`
(set `CBV_DATA_DIR` to change this). Put your own test books in `samples/`; that folder is
git-ignored.

## Licenses

The backend uses `python-chess` (GPL-3.0) and `PyMuPDF` (AGPL-3.0), and the frontend runs
Stockfish (`stockfish` npm package, GPL-3.0; copied to `frontend/public/engine/` on install) and
`chess.js` (BSD-2-Clause). That is fine for a personal local app; distributing the app as closed
source would mean replacing the GPL/AGPL parts.
