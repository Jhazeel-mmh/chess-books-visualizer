/** What the reader has solved in a book, saved with the book ("progress"). */

/** solved: right with no help; helped: right after a hint or a wrong try; failed: the solution was shown. */
export type Result = 'solved' | 'helped' | 'failed'

export interface ProblemRecord {
  result: Result
  tries: number
  hints: number
  ms: number
  /** When it was last done (ISO date). */
  at: string
}

/** One timed run through a set of problems (the Woodpecker Method repeats a set, faster each time). */
export interface Cycle {
  n: number
  /** The section the set is (its title), or "" for all the problems of the book. */
  set: string
  started: string
  finished?: string
  /** The problems of the set, in order (diagram keys). */
  problems: string[]
  results: Record<string, { result: Result; ms: number }>
}

export interface GuessRecord {
  /** Moves that were the game's, as good as the game's (by the engine), and all moves guessed. */
  same: number
  good: number
  total: number
  at: string
}

export interface Progress {
  /** By diagram key (stable when the book is analysed again). */
  problems: Record<string, ProblemRecord>
  cycles: Cycle[]
  /** Guess-the-move scores, by game title. */
  guesses: Record<string, GuessRecord>
}

export const EMPTY_PROGRESS: Progress = { problems: {}, cycles: [], guesses: {} }

/** Older or partial saved data with every field present. */
export function complete(p: Partial<Progress>): Progress {
  return { problems: p.problems ?? {}, cycles: p.cycles ?? [], guesses: p.guesses ?? {} }
}

/** The cycle still running for a set, if any. */
export function openCycle(p: Progress): Cycle | undefined {
  const last = p.cycles[p.cycles.length - 1]
  return last && !last.finished ? last : undefined
}

export function cycleTime(c: Cycle): number {
  return Object.values(c.results).reduce((sum, r) => sum + r.ms, 0)
}

/** "1:05", "12:40", "1:02:03". */
export function formatTime(ms: number): string {
  const s = Math.round(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`
}

/** The current time as saved in progress (ISO date). */
export function isoNow(): string {
  return new Date().toISOString()
}
