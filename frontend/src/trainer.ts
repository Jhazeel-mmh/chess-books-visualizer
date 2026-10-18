/**
 * The daily trainer's rules, kept free of React so they can be tested: grading a whole calculated
 * line, the goal and result of an endgame played out against the engine, and what a session leaves
 * in the trainer's record (positions tried, reading and game progress, difficulty, history).
 */

import { Chess } from 'chess.js'
import type {
  Attempt, BlockKind, CalcResult, Goal, ItemResult, LineNode, MoveNode, PlayResult, RunningSession, SessionPlan,
  SessionRecord, TrainerRecord,
} from './api'
import { flip, scoreValue, type EngineLine, type Score } from './engine'
import { isAsGood, judge, JUDGE_MS, mainLine, play, type BookTree, type EngineLike, type Move, type Verdict } from './solve'

export function treeOf(nodes: LineNode[]): BookTree {
  return new Map(nodes.map((n) => [n.id, { ...n, refs: [] } as MoveNode]))
}

export interface LineGrade {
  result: CalcResult
  /** What the judge said of the first move. */
  first: Verdict
  /** The reader expected a weaker reply than the best defence: the book's (or the engine's) reply instead (SAN). */
  missedDefence?: string
  /** The reader's line stopped before the book's did: how the book goes on (SAN). */
  goesOn?: string[]
  /** The reader's later move is worse than the book's: the book's (or the engine's) move (SAN). */
  bookMove?: string
  /** How many of the reader's moves the book doesn't give, but the engine finds as good. */
  byEngine: number
  /** Off the book's path, the line stopped before the combination was over. */
  short?: boolean
}

const toMove = (uci: string): Move => ({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] })

function sanOf(fen: string, uci: string | undefined): string | undefined {
  if (!uci) return undefined
  try {
    return new Chess(fen).move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] ?? 'q' }).san
  } catch {
    return undefined
  }
}

/** The engine, asked once per position: the judge and the defence check look at the same ones. */
function remembering(engine: EngineLike | null): EngineLike | null {
  if (!engine) return null
  const seen = new Map<string, Promise<EngineLine[]>>()
  return {
    analyse(fen, options) {
      const key = `${fen}|${options.movetime ?? ''}|${options.multipv ?? 1}`
      if (!seen.has(key)) seen.set(key, engine.analyse(fen, options))
      return seen.get(key)!
    },
  }
}

/**
 * Is the reply the reader expected as good for the defender as the best defence? If not, the best
 * defence (UCI). Without the engine a reply the book doesn't give can't be checked, so it isn't.
 */
async function defends(fen: string, afterFen: string, engine: EngineLike | null): Promise<{ ok: boolean; best?: string }> {
  if (!engine) return { ok: false }
  const best = (await engine.analyse(fen, { movetime: JUDGE_MS }))[0]
  const answer = (await engine.analyse(afterFen, { movetime: JUDGE_MS }))[0]
  if (!best || !answer) return { ok: false }
  return isAsGood(best.score, flip(answer.score)) ? { ok: true } : { ok: false, best: best.pv[0] }
}

/**
 * Grades a whole line the reader calculated (both sides' moves, UCI) against the book's solution,
 * move by move. The reader's own moves count when the book gives them, when they mate, or when the
 * engine finds them as good as the best (a rook on one file or the next). The replies the reader
 * expected count when the book gives them or when the engine finds them as good a defence as the
 * best one: expecting a weaker defence is a miss. "full" when the line gets to the end of the
 * combination (or mates), "first" when only the first move is right, "wrong" otherwise.
 */
export async function gradeLine(fen: string, line: string[], tree: BookTree, root: string, engine: EngineLike | null): Promise<LineGrade> {
  if (!line.length) return { result: 'wrong', first: { kind: 'wrong' }, byEngine: 0 }
  const mateLine = endsInMateFrom(tree, root)
  const bookLength = mainLine(tree, root).length
  const ask = remembering(engine)
  let node: string | undefined = root // where the book stands; undefined once off its path
  let pos = fen
  let first: Verdict = { kind: 'wrong' }
  let byEngine = 0
  for (let i = 0; i < line.length; i++) {
    const children = node ? (tree.get(node)?.children ?? []).map((id) => tree.get(id)!).filter(Boolean) : []
    if (node && i > 0 && !children.length) return { result: 'full', first, byEngine } // past the end of the book's line
    const after = play(pos, toMove(line[i]))
    if (!after) break
    if (i % 2 === 0) {
      const v = await judge(pos, toMove(line[i]), tree, node, mateLine, ask)
      if (i === 0) first = v
      if (v.kind === 'wrong' || v.kind === 'refuted') {
        if (i === 0) return { result: 'wrong', first, byEngine }
        const better = children[0]?.san ?? sanOf(pos, v.kind === 'wrong' ? v.best : undefined)
        return { result: 'first', first, byEngine, bookMove: better ?? undefined }
      }
      if (v.kind === 'engine') byEngine++
      if (v.kind === 'mate' || after.mate) return { result: 'full', first, byEngine }
      node = v.kind === 'book' || v.kind === 'alternative' ? v.node : undefined
    } else {
      const hit = children.find((c) => c.uci === after.uci)
      if (hit) node = hit.id
      else {
        const d = await defends(pos, after.fen, ask)
        if (!d.ok) return { result: 'first', first, byEngine, missedDefence: children[0]?.san ?? sanOf(pos, d.best) }
        node = undefined
      }
    }
    pos = after.fen
  }
  if (node !== undefined) {
    const rest = mainLine(tree, node)
    // Only the opponent's last reply left (or nothing): the reader saw it all.
    if (rest.length <= 1) return { result: 'full', first, byEngine }
    return { result: 'first', first, byEngine, goesOn: rest.map((n) => n.san ?? '') }
  }
  // Off the book's path, every move held up: it counts if the line is as long as the book's.
  return line.length >= bookLength - 1 ? { result: 'full', first, byEngine } : { result: 'first', first, byEngine, short: true }
}

function endsInMateFrom(tree: BookTree, root: string): boolean {
  const line = mainLine(tree, root)
  const last = line[line.length - 1]
  return !!last && new Chess(last.fen).isCheckmate()
}

// --- Endgames played out against the engine ---

/** At least this much (for the side to move) and the goal is to win; otherwise to hold the draw. */
export const WIN_CP = 150
/** The reader's moves before a play-out stops. */
export const PLAY_MOVES = 40

export function goalOf(score: Score): Goal {
  return scoreValue(score) >= WIN_CP ? 'win' : 'draw'
}

export type PlayEnd =
  | { kind: 'mate'; readerWon: boolean }
  | { kind: 'draw' }
  /** Out of moves: the engine's score for the reader then. */
  | { kind: 'limit'; score: Score }
  | { kind: 'resigned' }

export function playOutResult(goal: Goal, end: PlayEnd): PlayResult {
  if (end.kind === 'resigned') return 'failed'
  if (end.kind === 'mate') return end.readerWon ? 'met' : 'failed'
  if (end.kind === 'draw') return goal === 'draw' ? 'met' : 'failed'
  const v = scoreValue(end.score)
  if (goal === 'win') return v >= 300 ? 'partial' : 'failed'
  return v >= -100 ? 'met' : v >= -300 ? 'partial' : 'failed'
}

// --- Scores ---

const CALC_SCORE: Record<CalcResult, number> = { full: 1, first: 0.5, wrong: 0 }
const PLAY_SCORE: Record<PlayResult, number> = { met: 1, partial: 0.5, failed: 0 }

/** A share (0–1) for one block's results; null when there is nothing to score. */
export function blockScore(results: ItemResult[]): number | null {
  const scores: number[] = []
  let same = 0
  let total = 0
  for (const r of results) {
    if (r.kind === 'calculation') scores.push(CALC_SCORE[r.result])
    if (r.kind === 'endgame') scores.push(PLAY_SCORE[r.result])
    if (r.kind === 'guess') {
      same += r.same + r.good
      total += r.total
    }
  }
  if (total) scores.push(same / total)
  return scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : null
}

/** Studer's target: right 60–80% of the time. Above it the positions get harder, below it easier. */
export const TARGET = [0.6, 0.8] as const
const LEVEL_STEP = 0.25

export function adaptLevel(level: number, results: CalcResult[]): number {
  if (results.length < 2) return level
  const score = results.reduce((s, r) => s + CALC_SCORE[r], 0) / results.length
  const next = score > TARGET[1] ? level + LEVEL_STEP : score < TARGET[0] ? level - LEVEL_STEP : level
  return Math.min(6, Math.max(1, next))
}

// --- The record ---

export function startSession(record: TrainerRecord, plan: SessionPlan, now: string): TrainerRecord {
  const current: RunningSession = { plan, started: now, block: 0, item: 0, blockStarted: now, results: plan.blocks.map(() => []) }
  return { ...record, current }
}

/** What one finished item leaves: the position tried, how far the reading or the game got. */
export function noteItem(record: TrainerRecord, result: ItemResult, now: string): TrainerRecord {
  if (result.kind === 'calculation' || result.kind === 'endgame') {
    const id = `${result.book}:${result.key}`
    const attempt: Attempt = { at: now, result: result.result }
    return { ...record, positions: { ...record.positions, [id]: [...(record.positions[id] ?? []), attempt] } }
  }
  if (result.kind === 'reading') {
    return { ...record, reading: { book: result.book, at: { ...record.reading.at, [result.book]: result.to } } }
  }
  const id = `${result.book}:${result.game}`
  return { ...record, games: { current: id, at: { ...record.games.at, [id]: result.at } } }
}

/** Records an item's result and moves the running session on (to the next item, or block). */
export function advance(record: TrainerRecord, result: ItemResult | null, now: string): TrainerRecord {
  const cur = record.current
  if (!cur) return record
  let next = result ? noteItem(record, result, now) : record
  const results = cur.results.map((r, i) => (i === cur.block && result ? [...r, result] : r))
  const items = cur.plan.blocks[cur.block]?.items.length ?? 0
  const moreItems = cur.item + 1 < items
  const current: RunningSession = moreItems
    ? { ...cur, item: cur.item + 1, results }
    : { ...cur, block: cur.block + 1, item: 0, blockStarted: now, results }
  next = { ...next, current }
  return next
}

/** Skips the rest of the running block. */
export function skipBlock(record: TrainerRecord, now: string): TrainerRecord {
  const cur = record.current
  if (!cur) return record
  return { ...record, current: { ...cur, block: cur.block + 1, item: 0, blockStarted: now } }
}

/**
 * Drops the running session: it goes into no history, streak or difficulty. What already happened
 * stays (positions seen, where the reading or the game stopped), since it did happen.
 */
export function cancelSession(record: TrainerRecord): TrainerRecord {
  return { ...record, current: null }
}

export function sessionDone(cur: RunningSession): boolean {
  return cur.block >= cur.plan.blocks.length
}

/** Closes the running session: into the history, with the reader's focus and note; the level follows the results. */
export function finishSession(record: TrainerRecord, focus: number | null, note: string, now: string): TrainerRecord {
  const cur = record.current
  if (!cur) return record
  const session: SessionRecord = {
    id: cur.plan.id,
    test: cur.plan.test,
    started: cur.started,
    finished: now,
    ms: Date.parse(now) - Date.parse(cur.started),
    results: cur.results,
    kinds: cur.plan.blocks.map((b) => b.kind),
    focus,
    note,
  }
  const calc = cur.results.flat().flatMap((r) => (r.kind === 'calculation' ? [r.result] : []))
  const level = adaptLevel(record.level ?? cur.plan.level, calc)
  return { ...record, level, sessions: [...record.sessions, session], current: null }
}

// --- History ---

const day = (iso: string) => iso.slice(0, 10)

/** Days in a row with a finished session, up to today (or yesterday, if today's is still to come). */
export function streak(sessions: SessionRecord[], now: Date): number {
  const days = new Set(sessions.map((s) => day(s.finished)))
  const d = new Date(now)
  if (!days.has(day(d.toISOString()))) d.setUTCDate(d.getUTCDate() - 1)
  let n = 0
  while (days.has(day(d.toISOString()))) {
    n++
    d.setUTCDate(d.getUTCDate() - 1)
  }
  return n
}

export interface WeekStats {
  /** Monday of the week (YYYY-MM-DD). */
  week: string
  sessions: number
  minutes: number
  /** Scores (0–1) per kind of block, null if not trained that week. */
  scores: Record<Exclude<BlockKind, 'reading'>, number | null>
  pages: number
}

function monday(iso: string): string {
  const d = new Date(iso)
  const back = (d.getUTCDay() + 6) % 7
  d.setUTCDate(d.getUTCDate() - back)
  return d.toISOString().slice(0, 10)
}

/** The last weeks' training, newest first. */
export function weekly(sessions: SessionRecord[], now: Date, weeks = 6): WeekStats[] {
  const out: WeekStats[] = []
  const start = new Date(monday(now.toISOString()))
  for (let w = 0; w < weeks; w++) {
    const d = new Date(start)
    d.setUTCDate(d.getUTCDate() - 7 * w)
    const key = d.toISOString().slice(0, 10)
    const these = sessions.filter((s) => monday(s.finished) === key)
    const all = these.flatMap((s) => s.results.flat())
    const of = (kind: BlockKind) => blockScore(all.filter((r) => r.kind === kind))
    out.push({
      week: key,
      sessions: these.length,
      minutes: Math.round(these.reduce((m, s) => m + s.ms, 0) / 60000),
      scores: { calculation: of('calculation'), endgame: of('endgame'), guess: of('guess') },
      pages: all.reduce((p, r) => p + (r.kind === 'reading' ? Math.max(0, r.to - r.from) : 0), 0),
    })
  }
  return out
}
