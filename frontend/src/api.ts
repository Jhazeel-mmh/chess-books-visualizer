export type BookStatus = 'queued' | 'analyzing' | 'ready' | 'error'

export interface Stats {
  moves_found: number
  moves_resolved: number
  games: number
  diagrams?: number
  diagrams_read?: number
  /** Diagrams worth a look in the reader, and those corrected from their solution. */
  diagrams_to_check?: number
  diagrams_fixed?: number
}

export interface BookMeta {
  id: string
  title: string
  filename: string
  format: string
  status: BookStatus
  error: string | null
  stats: Stats | null
  /** Fraction of the book read while analyzing. */
  progress?: number | null
  imported_at: string
}

/** [block index, start, end] of the text a move was read from. */
export type TextRef = [number, number, number]

export interface MoveNode {
  id: string
  parent: string | null
  /** Main continuation first. */
  children: string[]
  san: string | null
  uci: string | null
  /** Position after this move (the start position for the root). */
  fen: string
  nags: number[]
  mainline: boolean
  refs: TextRef[]
  /** Worked out from damaged OCR text everywhere the book prints it, so it may be wrong. */
  uncertain?: boolean
}

export interface Game {
  id: string
  title: string | null
  start_fen: string
  root: string
  nodes: MoveNode[]
}

export interface Unresolved {
  refs: TextRef[]
  text: string
  reason: 'no_game' | 'no_position' | 'illegal' | 'ambiguous' | 'number'
}

export interface Diagram {
  id: string
  block: number
  /** Stable name under which a correction is saved. */
  key: string | null
  /** The number printed next to the diagram ("165"), if any. */
  label: string | null
  /** FEN piece placement, when the diagram could be read. */
  placement: string | null
  /** Side to move when the book marks it. */
  turn: 'w' | 'b' | null
  /** Certainty of the least certain square (1 for typed diagrams and corrections). */
  confidence: number | null
  /** Squares worth checking, 0 = a8 … 63 = h1. */
  uncertain: number[]
  /** The move node whose position the diagram shows, if linked. */
  node: string | null
  /** Corrected by the app because only that reading fits the book's solution. */
  fixed?: boolean
  /** Why the diagram is worth a look: "fixed", "doubtful", "solution_failed", "mate_missed", "not_a_position", "unread". */
  check?: string[]
  /** Worth a look: listed by the reader's "only diagrams to check". */
  to_check?: boolean
  /** A problem to solve (the caption sets a task, a numbered solution refers to it, or it's in a section of exercises). */
  problem?: boolean
  /** Points the book gives it ("(3 points)"). */
  points?: number | null
  /** Title of the section of the book it is in. */
  section?: string | null
  /** The move node where the book's solution starts (none: the engine judges). */
  solution?: string | null
  corrected?: boolean
}

export interface Analysis {
  notation: {
    lang: string
    glyphs: Record<string, string>
    /** Scanned books: how the OCR junk spellings of pieces were read ("l:t" → "R"). */
    ocr?: { learned: Record<string, string>; guessed: Record<string, string>; unknown: number }
  }
  style: 'bold' | 'paragraph'
  games: Game[]
  unresolved: Unresolved[]
  diagrams: Diagram[]
  sections?: { block: number; title: string; kind: 'problems' | 'solutions' | null }[]
  stats: Stats
}

export interface EpubLayout {
  kind: 'epub'
  chapters: { href: string; title: string | null }[]
  /** Chapter index of every block. */
  blocks: number[]
}

export interface PdfLayout {
  kind: 'pdf'
  /** [width, height] of every page, in PDF points. */
  pages: [number, number][]
  /** The PDF's own table of contents: [level, title, page index]. */
  toc?: [number, string, number][]
  /** Page index of every block. */
  blocks: number[]
}

export type Layout = EpubLayout | PdfLayout

export type MarkKind = 'move' | 'unresolved' | 'diagram'

export interface PageMark {
  kind: MarkKind
  id: string
  /** [x0, y0, x1, y1] in PDF points. */
  rects: [number, number, number, number][]
  /** A move worked out from damaged OCR text rather than read. */
  uncertain?: boolean
  /** A move the reader entered (a move fix). */
  fixed?: boolean
}

/** A move the reader entered on a page (or a false move removed), saved with the book. */
export interface MoveFix {
  page: number
  /** [x0, y0, x1, y1] in PDF points: where the move is printed. */
  rect: [number, number, number, number]
  /** Position before the move (FEN) and the move (UCI); absent for a removal. */
  before?: string
  uci?: string
  san?: string
  remove?: boolean
}

// --- The daily trainer ---

export type BookRole = 'tactics' | 'endgames' | 'concepts' | 'games' | 'skip'
export type Focus = 'calculation' | 'endgames' | 'positional'
export type BlockKind = 'calculation' | 'endgame' | 'reading' | 'guess'
/** A calculation: the whole line right, only the first move, or wrong. */
export type CalcResult = 'full' | 'first' | 'wrong'
/** An endgame played out: the goal met, nearly (out of moves but on track), or not. */
export type PlayResult = 'met' | 'partial' | 'failed'
export type Goal = 'win' | 'draw'

/** A move of a book's line as the trainer sends it (no places in the book). */
export type LineNode = Omit<MoveNode, 'refs'>

export interface CalcItem {
  book: string
  bookTitle: string
  key: string
  diagram: string
  label: string | null
  fen: string
  root: string
  tree: LineNode[]
  difficulty: number
}
export interface EndgameItem {
  book: string
  bookTitle: string
  key: string
  fen: string
  pieces: number
}
export interface ReadingItem {
  book: string
  bookTitle: string
  kind: 'pdf' | 'epub'
  /** Page (PDF) or chapter (EPUB) where the reader left off, if known. */
  at: number | null
  length: number
}
export interface GuessItem {
  book: string
  bookTitle: string
  game: string
  title: string | null
  /** The game's main line, from its start. */
  line: LineNode[]
  /** Where to start guessing (index into the line) and how many moves to guess. */
  from: number
  moves: number
}

export type PlanBlock =
  | { kind: 'calculation'; minutes: number; items: CalcItem[] }
  | { kind: 'endgame'; minutes: number; items: EndgameItem[] }
  | { kind: 'reading'; minutes: number; items: ReadingItem[] }
  | { kind: 'guess'; minutes: number; items: GuessItem[] }

export interface SessionPlan {
  id: string
  test: boolean
  level: number
  planned: number
  blocks: PlanBlock[]
}

export type ItemResult =
  | { kind: 'calculation'; book: string; key: string; result: CalcResult; ms: number; line: string[] }
  | { kind: 'endgame'; book: string; key: string; result: PlayResult; goal: Goal; ms: number }
  | { kind: 'reading'; book: string; from: number; to: number; ms: number }
  | { kind: 'guess'; book: string; game: string; same: number; good: number; total: number; at: number; ms: number }

export interface RunningSession {
  plan: SessionPlan
  started: string
  /** Where the session is: the block and the item in it. */
  block: number
  item: number
  blockStarted: string
  results: ItemResult[][]
}

export interface SessionRecord {
  id: string
  test: boolean
  started: string
  finished: string
  ms: number
  results: ItemResult[][]
  kinds: BlockKind[]
  /** How focused the reader was (1–10) and what to work on next. */
  focus: number | null
  note: string
}

export interface Attempt {
  at: string
  result: CalcResult | PlayResult
}

export interface TrainerRecord {
  settings: { minutes: number; rating: number; focus: Focus | null }
  /** Difficulty of calculation positions (1–6); set from the rating at first, then follows the results. */
  level: number | null
  roles: Record<string, BookRole>
  /** Every position tried, by "book:key". */
  positions: Record<string, Attempt[]>
  reading: { book: string | null; at: Record<string, number> }
  games: { current: string | null; at: Record<string, number> }
  /** The books picked for each subject; a subject not listed takes its books by their roles. */
  sources: Partial<Record<BlockKind, string[]>>
  sessions: SessionRecord[]
  current: RunningSession | null
}

export interface TrainerBook {
  id: string
  title: string
  kind: 'pdf' | 'epub'
  role: BookRole
  /** What each subject can take from the book: problems, endgame positions, pages or chapters, games. */
  material: Record<BlockKind, number>
  /** Whether the next session draws from it, for each subject. */
  uses: Record<BlockKind, boolean>
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.status === 204 ? (undefined as T) : res.json()
}

export const api = {
  books: () => request<BookMeta[]>('/api/books'),
  book: (id: string) => request<BookMeta>(`/api/books/${id}`),
  analysis: (id: string) => request<Analysis>(`/api/books/${id}/analysis`),
  upload: (file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<BookMeta>('/api/books', { method: 'POST', body })
  },
  remove: (id: string) => request<void>(`/api/books/${id}`, { method: 'DELETE' }),
  reanalyze: (id: string) => request<BookMeta>(`/api/books/${id}/analyze`, { method: 'POST' }),
  correctDiagram: (id: string, key: string, placement: string, turn: 'w' | 'b') =>
    request<BookMeta>(`/api/books/${id}/diagrams`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, placement, turn }),
    }),
  layout: (id: string) => request<Layout>(`/api/books/${id}/layout`),
  pageMarks: (id: string, page: number) => request<PageMark[]>(`/api/books/${id}/pages/${page}/marks`),
  pageUrl: (id: string, page: number) => `/api/books/${id}/pages/${page}.png?zoom=2`,
  epubUrl: (id: string, href: string) => `/api/books/${id}/epub/${href.split('/').map(encodeURIComponent).join('/')}`,
  pgnUrl: (bookId: string, gameId: string) => `/api/books/${bookId}/games/${gameId}.pgn`,
  trainer: () => request<TrainerRecord>('/api/trainer'),
  saveTrainer: (record: TrainerRecord) =>
    request<void>('/api/trainer', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(record) }),
  trainerBooks: () => request<TrainerBook[]>('/api/trainer/books'),
  newSession: (test: boolean) => request<SessionPlan>(`/api/trainer/session?test=${test}`, { method: 'POST' }),
  moveFixes: (id: string) => request<MoveFix[]>(`/api/books/${id}/move-fixes`),
  saveMoveFixes: (id: string, fixes: MoveFix[]) =>
    request<BookMeta>(`/api/books/${id}/move-fixes`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(fixes),
    }),
  /** What the reader saved for a book: "progress" (solving) or "annotations" (arrows and circles). */
  userData: <T>(id: string, name: UserData) => request<T>(`/api/books/${id}/user/${name}`),
  saveUserData: (id: string, name: UserData, data: unknown) =>
    request<void>(`/api/books/${id}/user/${name}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
}

export type UserData = 'progress' | 'annotations'


