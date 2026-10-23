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
- **Mangled text.** Split numbers (`1 1.0-0` is move 11, `1 O.` is 10), a dot read as `J`
  (`10JWe2`), split squares (`d 5`), two moves without a space (`1.e4e6`), a `[` that is a
  bishop, and an origin glued to a junk spelling (`13bc8`: the rook from the b-file) are read
  as printed. A bare pawn move (`e5`) is never a capture: captures print their file.
- **Figurines read by their shape.** The same knight may be spelled `T`, `tLl` or `4J` from
  page to page, but it is printed clearly: the figurines of moves already linked are cropped
  from the page and labelled, and every other figurine is read by the labelled shapes nearest
  to it (`cbv/vision/figurines.py`). This second reading is kept only if it reads the book
  better; the shapes are cached in `glyphs.npz` next to the book.
- **Moves worked out from what follows** (`cbv/parse/decoder.py`). Where a fragment still
  breaks, every legal move is scored against the print (square and its look-alikes, piece,
  capture, origin, check), and a search keeps the best few sequences. A worked-out move is
  taken only when the moves printed after it bear it out, more of them when the print looked
  clean, and only when no other reading fits nearly as well; it is shown as uncertain.
- **A broken main line picked up again.** When a game's main line breaks off, its unread
  moves are read together with the next main-line paragraph (`9.Bg3 Bg7 10.Qe2 Ne7` decides
  the garbled 7...Qc7 before it). A game also starts from a garbled first move.
- **Puzzle numbers** are read from captions such as `123) Black to play` (also `123}`) and
  exercise numbers such as `2.05`, each caption going to its closest diagram.

On the sample library, moves linked in the scanned books: Nunn 70%, De la Villa 49%, Gulko
39%, Nimzovich's *Mi sistema* 31% (from 65%, 44%, 29% and 22%), with more of the linked moves
agreeing with the checks and captures the book prints. Two tools measure this:
`make report-library` reads every book of the library again in memory and compares it with
the numbers kept by `make report-save`; `scripts/ocr_bench.py` damages a clean digital book the
way OCR does and checks every move read from the damaged text against the clean one (on the
sample EPUB: 61% of the moves read back, 92% of them right). Very poor OCR still leaves many
moves unlinked: those can be completed with *Fix moves*.

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

## Running it as a website

By default the app is local: one reader, no sign-in. With `CBV_HOSTED=1` it serves many people,
and each one signs in and sees only their own books:

- **Accounts:** sign-up is confirmed by a link sent to the email, and passwords are reset the
  same way. Passwords are kept as Argon2id hashes; sessions and mailed links only as hashes of
  their tokens. Nothing tells a visitor whether an email has an account.
- **Separate libraries:** each account's books, analyses, notes and training record are in
  `<data>/users/<account id>/`. A request only looks in its own account's library, so another
  reader's book answers 404. The same file imported by two people is two separate copies.
- **Sessions:** an HttpOnly, Secure, SameSite=Lax cookie. Requests that change something are
  refused when they come from another site.
- **Signing up** accepts the terms of use (the server refuses a sign-up without). An account whose
  email nobody confirms is forgotten after 7 days.
- **Closing an account** (confirmed with the password) deletes the account and its whole library.
- **Signing out** also makes the browser forget where that reader was in each book.

| Setting | What it is |
|---|---|
| `CBV_HOSTED=1` | Turns accounts on. |
| `CBV_PUBLIC_URL` | The site's address (`https://…`): for the links in emails, the cross-site check and the legal pages. |
| `CBV_SMTP_HOST`, `CBV_SMTP_PORT`, `CBV_SMTP_USER`, `CBV_SMTP_PASSWORD`, `CBV_MAIL_FROM` | The mail server. Without one, mail is only written to the server log. |
| `CBV_COPYRIGHT_EMAIL` | The copyright agent's address: copyright notices and counter-notices are sent there as they arrive. |
| `CBV_OPERATOR`, `CBV_OPERATOR_ADDRESS` | Who runs the site (a person's or a company's legal name) and their postal address, as the legal pages name them. |
| `CBV_CONTACT_EMAIL` | Where privacy requests and anything else go. |
| `CBV_COPYRIGHT_AGENT` | The copyright agent as registered with the US Copyright Office: name, postal address, phone. |
| `CBV_COOKIE_SECURE=0` | Only to try the hosted mode over plain HTTP. |
| `CBV_MAX_UPLOAD_MB` | The largest book file (default 100). |
| `CBV_MAX_BOOKS`, `CBV_MAX_STORAGE_MB` | What a free account may keep: books (default 3), and their files together (default 300 MB). |
| `CBV_PLUS_MAX_BOOKS`, `CBV_PLUS_MAX_STORAGE_MB` | The same for Plus (defaults 300 books, 5000 MB). |
| `CBV_FREE_TRAINER_SESSIONS` | Daily-trainer sessions a free account may start, once and for all (default 7). Counted only while Plus is on sale. |
| `CBV_PADDLE_API_KEY`, `CBV_PADDLE_CLIENT_TOKEN`, `CBV_PADDLE_PRICE`, `CBV_PADDLE_WEBHOOK_SECRET` | Selling Plus through Paddle (see Plans and ads). Without all four, nothing is sold. |
| `CBV_PADDLE_SANDBOX=1` | Uses Paddle's test environment (sandbox keys and test cards). |
| `CBV_ADSENSE_CLIENT`, `CBV_ADSENSE_SLOT` | Google AdSense's publisher id (`ca-pub-…`) and a display ad unit's id. Without both, no ads. |
| `CBV_ANALYSIS_MINUTES`, `CBV_ANALYSIS_MEMORY_MB` | When a book's analysis is stopped (defaults 20 minutes, and 4096 MB of address space). |
| `CBV_WORKERS` | How many books are analysed at once (default 2). |
| `VITE_SOURCE_URL` | When building the frontend: the public repository (see License). |

The limits apply only when hosted (the local app has none); 0 turns one off. Changing one is
changing the setting and restarting the app: there is no admin page.

Try it locally with a separate data folder, so your own library isn't mixed in:
`CBV_HOSTED=1 CBV_DATA_DIR=/tmp/cbv-hosted CBV_COOKIE_SECURE=0 make dev`. The sign-up links
appear in the backend's log.

### Keeping the server up

Anyone can sign up, so the site expects some uploads and requests to be hostile:

- **Uploads** are copied to disk a piece at a time, and stopped past `CBV_MAX_UPLOAD_MB` (Caddy
  stops them first). What a file is comes from its content, not its name: only PDF and EPUB are
  taken. An EPUB is a zip file, and one that would unpack to more than 1 GB or 10,000 files (a
  "zip bomb") is refused. Other request bodies are at most 16 MB.
- **Quotas:** a free account keeps at most `CBV_MAX_BOOKS` books, and `CBV_MAX_STORAGE_MB` of
  book files; Plus, `CBV_PLUS_MAX_*`. The library shows how much is used.
- **Analysis in worker processes** (`backend/cbv/jobs.py`): each book is read in a process of its
  own, at a lower priority than the server. It is stopped past `CBV_ANALYSIS_MINUTES` or
  `CBV_ANALYSIS_MEMORY_MB`, and the book shows why. A file that crashes or hangs the PDF reader
  fails alone. At most `CBV_WORKERS` books are read at once, one per account, with accounts taking
  turns. The sample books need at most 5 minutes and 3 GB of address space (the readers reserve
  1.5 GB of it before reading anything).
- **Rate limits** (`backend/cbv/ratelimit.py`), counted in the server's memory:

  | What | How often |
  |---|---|
  | Sign-in | 20 tries per 10 minutes from one address; 10 wrong passwords per 15 minutes for one account, from anywhere |
  | Sign-up | 10 per hour from one address |
  | Mail (confirmation, password reset) | 5 per hour to one address, 10 requests per hour from one |
  | Deleting the account | 10 password checks per hour |
  | Uploads | 30 per hour per account |
  | Copyright notices | 5 per hour from one address |

  An IPv6 client counts as its whole /64. The server must run as one process: with two, each
  would count apart. The addresses and emails counted are never written to disk, and are
  forgotten an hour after their last try (the privacy notice says so).
- **Page images** of a PDF are drawn at the one size the app shows, with at most 25 million
  pixels (a PDF page can say it is 5 m wide). They are kept while someone looks at them: `purge`
  deletes the ones nobody opened in 7 days.

### Deploying

`Dockerfile` builds two images, and `deploy/compose.yaml` runs them on one server:

- **app:** the API, run by uvicorn as one process, with the data in a Docker volume. It keeps no
  access log, and Caddy neither: the privacy notice says so. Docker keeps what the containers
  print, at most 30 MB each.
- **web:** Caddy. It gets HTTPS certificates from Let's Encrypt, sends HSTS and other security
  headers, serves the built frontend, and passes `/api` (and `/ads.txt`) to the app with the
  client's real address.
- **purge:** runs `scripts/admin.py purge` once a day.

```sh
cp deploy/site.env.example deploy/site.env    # fill in the domain, mail server and repository
docker compose -f deploy/compose.yaml --env-file deploy/site.env up -d --build
docker compose -f deploy/compose.yaml exec app python /app/scripts/admin.py notices
```

A worker can use about 2.5 GB of real memory before its limit stops it (the sample books needed at
most 1.1 GB). With the default two workers, give the server at least 6 GB, and 8 GB to be
comfortable.

### Legal pages

A hosted site shows, in its footer and on the sign-up form, its terms of use (`/terms`), privacy
notice (`/privacy`, the *aviso de privacidad* of Mexico's LFPDPPP) and copyright policy
(`/copyright/policy`). They are written in Spanish, the version that prevails, and translated to
English, in `frontend/src/policies/*.md`. Their blanks (`{operator}`, `{strikes}`…) are filled from
the settings above and from the rules in the code, through `/api/legal`; a setting that isn't set
shows its name in red, and the server warns at start-up. A test checks that both languages have the
same sections, blanks and links.

They are drafts, written for a Mexican lawyer to review before the site opens. What they say about
the data must stay true of the code: when the code starts keeping something new, or keeping it for
longer, change the privacy notice in the same change.

### Plans and ads

A hosted site has two plans, shown to anyone at `/plans`: the free plan, and **Plus**, a
subscription that gives more books and storage, an unlimited daily trainer and no ads. A free
account may try the trainer `CBV_FREE_TRAINER_SESSIONS` times; the reader, the problems and the
cycles are free and unlimited on both. When Plus ends nothing is deleted: the books stay readable,
and new ones fit once the library is back within the free plan.

**Payments** (`backend/cbv/billing.py`) go through [Paddle](https://www.paddle.com), the
merchant of record: Paddle sells Plus to the reader, charges the taxes of their country, invoices
and refunds them, and pays the site. The site never sees a card; it keeps Paddle's customer and
subscription ids, the status and the dates. To sell Plus:

1. In Paddle (start with its sandbox and `CBV_PADDLE_SANDBOX=1`), create the product and its
   recurring price (`pri_…`: `CBV_PADDLE_PRICE`); its amount, currency, period and any free trial
   are set there, and `/plans` shows them.
2. Create an API key (`CBV_PADDLE_API_KEY`) that can read prices, create customer portal sessions
   and cancel subscriptions, and a client-side token (`CBV_PADDLE_CLIENT_TOKEN`).
3. Add a notification destination for `https://<domain>/api/billing/webhook` with the
   `subscription.*` events; its secret key is `CBV_PADDLE_WEBHOOK_SECRET`. The app refuses any
   webhook not signed with it, or signed more than 5 minutes before.
4. Set the default payment link to `https://<domain>/plans`, and have Paddle approve the domain.
   Paddle reviews the site: the plans page, the terms (which name Paddle as merchant of record and
   explain renewal and cancelling) and the privacy notice are there for that.

The browser opens Paddle's checkout over `/plans` with the account's id in its custom data, and
Paddle's webhooks tell the server what became of the subscription. The account page opens
Paddle's customer portal (invoices, the card) and has a one-click “Cancel subscription”: cancelling
is as easy as subscribing, as Mexico's consumer law asks. Deleting an account cancels its
subscription first, at once, and the account isn't deleted if Paddle can't be told. Closing an
account (copyright strikes, `admin.py close`) cancels it too, or says to do it in Paddle's
dashboard.

**Ads** (`frontend/src/components/AdSlot.tsx`) are Google AdSense display units, for free
accounts, only on pages that show nothing of a book: the library, and the trainer's start and
summary. Never in the reader, the solver or a trainer block: AdSense allows no ads beside content
the site has no rights to, and a host that earns money from its users' infringing uploads loses
the law's protection. A test checks which pages have them. The AdSense script loads only when the
first ad is shown. In AdSense:

- turn **Auto ads off**: they would place ads anywhere, the reader too;
- create a GDPR message in **Privacy & messaging**: Google's certified consent banner for visitors
  from the EEA, the UK and Switzerland;
- leave third-party ad serving off, or name those vendors in the privacy notice.

The app serves `/ads.txt` from `CBV_ADSENSE_CLIENT`.

### Copyright notices

A site that keeps what its users upload is protected from their copyright infringements only if
it acts on notices: Mexico's LFDA (arts. 114 Septies and 114 Octies) and the US DMCA (§ 512) both
ask for this. The process is in `backend/cbv/copyright.py`:

- **On upload** the reader confirms that the book is theirs to use, for their own study only.
  When they did is kept with the book.
- **Notices:** anyone can send one with the form at `/copyright` (linked from the copyright policy). It asks
  for what the LFDA and the DMCA require. A rights holder can't see anyone's uploads, so they name
  the work. They can also pick their copy of the file: the browser sends only its SHA-256
  fingerprint, never the file.
- **Takedowns:** the copyright agent runs `scripts/admin.py` on the server, with the app's
  settings, to find the uploads a notice names and disable them. The owner still sees a disabled
  book listed but can't open it (the server answers 451). They get an email saying why, and how to
  answer with a counter-notice. The agent can also block a file's fingerprint, so nobody can
  upload it again.
- **Counter-notices:** the agent forwards them to whoever sent the notice, and restores the book
  after 15 business days (the LFDA's term; weekends and Mexico's official holidays don't count)
  unless that person shows they started a court or administrative action, a criminal complaint or
  mediation.
- **Rejected notices:** `reject N "why"` tells whoever sent the notice why it won't be acted on.
- **Strikes:** each notice that disables an account's books is a strike until the books are
  restored. At 3 strikes the account is closed. Strikes stay with the email, even if the account
  is deleted and created again.
- **Deletion:** `purge` deletes disabled books nobody answered for within 30 days, and the
  libraries of accounts closed more than 30 days ago.

```
python scripts/admin.py notices              # new notices; then: notice N, find --notice N | --title "…"
python scripts/admin.py disable N BOOK...    # takes down every copy of those books (--account EMAIL: one)
python scripts/admin.py counters             # then: counter C, forward C, restore T [--now]
python scripts/admin.py account EMAIL        # an account's books, takedowns and strikes
python scripts/admin.py purge                # daily: the purge service of deploy/compose.yaml runs it
```

## License

Chess Books Visualizer is free software under the GNU Affero General Public License, version 3
or later (see `LICENSE`). It has to be: the backend reads PDFs with `PyMuPDF` (AGPL-3.0) and
moves with `python-chess` (GPL-3.0), and the browser runs Stockfish (`stockfish` npm package,
GPL-3.0).

What the AGPL asks of a site that runs it for others, and how the app does it:

- **Source code for every user.** Build the frontend with `VITE_SOURCE_URL` set to the public
  repository; the footer and the Licenses page (`/licenses`) link to it.
- **Stockfish's license and source.** Its license is copied next to the engine
  (`/engine/Copying.txt`) and the Licenses page links its exact source.
- **Notices of the other libraries.** The Licenses page lists the server's libraries
  (`/api/licenses`, read from what is installed) and the browser's, with their license texts
  (`/licenses.json`, written by `frontend/scripts/notices.mjs` before every dev run and build).
- **The pieces.** The drawings are Colin M. L. Burnett's (GPL, BSD or GFDL), credited on the
  Licenses page.
