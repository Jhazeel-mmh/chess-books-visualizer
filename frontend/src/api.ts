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
  /** Hosted app: when the reader said the book is theirs to use. */
  declared_at?: string
  /** Disabled after a copyright notice: listed, but it can't be opened. */
  disabled?: Disabled
}

export interface Disabled {
  at: string
  /** Who the notice was sent for, and the work it named. */
  claimant: string
  work: string
  /** When its owner sent a counter-notice. */
  counter_at?: string
}

/** A copyright notice, as the form at /copyright sends it. */
export interface CopyrightNotice {
  name: string
  email: string
  phone: string
  address: string
  /** The rights holder it is sent for. */
  claimant: string
  work: string
  location: string
  /** SHA-256 of the sender's copy of the file, worked out in the browser. */
  sha256: string | null
  signature: string
  good_faith: true
  accurate: true
  lang: string
}

/** The answer of a disabled book's owner. */
export interface CounterNotice {
  name: string
  address: string
  phone: string
  reason: string
  signature: string
  good_faith: true
  jurisdiction: true
  lang: string
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

/** A library the app is built from, with its license (for the Licenses page). */
export interface Package {
  name: string
  version: string
  license: string | null
  /** Its source (browser libraries) or home page (server libraries). */
  repository?: string | null
  home?: string | null
  /** The license text the package ships (browser libraries). */
  text?: string | null
}

/** Who is signed in: the local app has no accounts; a hosted one shows its sign-in page to nobody. */
export interface Me {
  hosted: boolean
  user: { email: string } | null
}

/** What a hosted account keeps, and the most it may (0: no limit). */
export interface Usage {
  books: number
  bytes: number
  max_books: number
  max_bytes: number
  max_upload: number
}

/** What a hosted site's legal pages fill their blanks with (null: not set on the server). */
export interface Legal {
  site: string
  operator: string | null
  address: string | null
  contact: string | null
  copyright_email: string | null
  copyright_agent: string | null
  strikes: number
  keep_days: number
  wait_days: number
  session_days: number
  unverified_days: number
  render_days: number
}

/** A hosted account's plan: free, or Plus (sold through Paddle; see the backend's billing.py). */
export interface Plan {
  plus: boolean
  /** Paddle's status of the subscription: "active", "trialing", "past_due" (a payment failed), "canceled"… */
  status: string | null
  /** The end of the period paid for. */
  until: string | null
  /** When a cancellation the reader asked for takes effect. */
  cancel_at: string | null
  selling: boolean
  /** Paddle's customer portal can be opened: the account bought Plus once. */
  manage: boolean
  /** What Paddle's checkout opens with (null: Plus isn't on sale here, or the account has it). */
  checkout: Checkout | null
  /** The ad unit a free account sees on pages without a book (null: no ads). */
  ads: { client: string; slot: string } | null
  /** Trainer sessions a free account may still start (null: no limit). */
  trainer_left: number | null
}

export interface Paddle {
  token: string
  sandbox: boolean
}

export interface Checkout extends Paddle {
  price: string
  email: string
  user: string
}

/** Plus's price as Paddle has it: the amount in the currency's smallest unit (cents). */
export interface Price {
  amount: string
  currency: string
  interval: 'day' | 'week' | 'month' | 'year' | null
  frequency: number | null
  trial_interval: 'day' | 'week' | 'month' | 'year' | null
  trial_frequency: number | null
}

/** What each plan of a hosted site gives (0: no limit). */
export interface Plans {
  selling: boolean
  price: Price | null
  /** Paddle's client-side token, to open the checkout links Paddle sends (null: Plus isn't on sale). */
  paddle: Paddle | null
  ads: boolean
  upload_mb: number
  free: { books: number; storage_mb: number; trainer_sessions: number }
  plus: { books: number; storage_mb: number }
}

/** Sent when the server says the session is over (hosted app), so the app shows the sign-in page. */
export const SIGNED_OUT = 'cbv:signed-out'

export class ApiError extends Error {
  status: number
  /** The server's reason: "credentials", "unverified", "closed", "link", "email", "password", "terms" (account forms);
   *  "blocked", "disabled", "sent" (copyright); "too_big", "unpacked", "format", "books", "storage" (uploads);
   *  "too_many" (any form tried too often); "plus" (the free trainer sessions are spent);
   *  "billing" (Paddle didn't answer). */
  detail: string | null

  constructor(status: number, statusText: string, detail: string | null) {
    super(`${status} ${statusText}`)
    this.status = status
    this.detail = detail
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith('/api/auth/')) window.dispatchEvent(new Event(SIGNED_OUT))
    const detail = await res.json().then((b) => (typeof b?.detail === 'string' ? b.detail : null), () => null)
    throw new ApiError(res.status, res.statusText, detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const post = (url: string, body?: unknown) =>
  request<void>(url, body === undefined ? { method: 'POST' } : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  me: () => request<Me>('/api/auth/me'),
  /** ``terms``: the reader accepted the terms of use (the server refuses a sign-up without). */
  signUp: (email: string, password: string, lang: string, terms: boolean) => post('/api/auth/signup', { email, password, lang, terms }),
  resend: (email: string) => post('/api/auth/resend', { email }),
  verify: (token: string) => post('/api/auth/verify', { token }),
  signIn: (email: string, password: string) => post('/api/auth/login', { email, password }),
  forgot: (email: string) => post('/api/auth/forgot', { email }),
  reset: (token: string, password: string) => post('/api/auth/reset', { token, password }),
  signOut: () => post('/api/auth/logout'),
  deleteAccount: (password: string) => post('/api/auth/delete-account', { password }),
  books: () => request<BookMeta[]>('/api/books'),
  book: (id: string) => request<BookMeta>(`/api/books/${id}`),
  analysis: (id: string) => request<Analysis>(`/api/books/${id}/analysis`),
  /** ``rights``: the reader said the book is theirs to use (the hosted app asks). */
  upload: (file: File, rights = false) => {
    const body = new FormData()
    body.append('file', file)
    if (rights) body.append('rights', 'true')
    return request<BookMeta>('/api/books', { method: 'POST', body })
  },
  usage: () => request<Usage>('/api/usage'),
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
  copyrightNotice: (notice: CopyrightNotice) =>
    request<{ id: number }>('/api/copyright-notices', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(notice) }),
  counterNotice: (id: string, counter: CounterNotice) => post(`/api/books/${id}/counter-notice`, counter),
  plan: () => request<Plan>('/api/plan'),
  plans: () => request<Plans>('/api/plans'),
  /** Links into Paddle's customer portal, good for a short time. */
  portal: () => request<{ overview: string; cancel: string | null }>('/api/billing/portal', { method: 'POST' }),
  serverLicenses: () => request<Package[]>('/api/licenses'),
  legal: () => request<Legal>('/api/legal'),
  /** Written at build time by scripts/notices.mjs. */
  browserLicenses: () => request<{ packages: Package[] }>('/licenses.json').then((r) => r.packages),
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


