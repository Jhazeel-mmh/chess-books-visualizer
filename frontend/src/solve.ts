/**
 * Solving a problem from a book: judging the reader's moves against the book's solution,
 * and against the engine where the book doesn't say.
 *
 * The book's solution is a tree of moves (main line first). A move is right when it is the book's
 * main move, another move the book gives without a "?" or "??", any mate when the line is a mate,
 * or (by the engine) a move that keeps the same result. Kept free of React so it can be tested.
 */

import { Chess } from 'chess.js'
import type { MoveNode } from './api'
import { flip, scoreValue, type EngineLine, type Score } from './engine'

/** What the judge needs from the engine (the real one, or a stand-in in tests). */
export interface EngineLike {
  analyse(fen: string, options: { movetime?: number; multipv?: number }): Promise<EngineLine[]>
}

/** The book's solution: its moves by id. */
export type BookTree = Map<string, MoveNode>

/** How long the engine looks at a position when judging a move. */
export const JUDGE_MS = 1500
/** A move this many centipawns worse than the best (for the side that played it) still counts. */
export const TOLERANCE_CP = 30
/** A result this clear counts as won, whichever winning move keeps it. */
export const DECISIVE_CP = 300
/** A mate this many moves slower than the quickest still counts (a piece on one square or the next). */
export const MATE_SLACK = 1

export type Verdict =
  | { kind: 'book'; node: string } // the book's main move
  | { kind: 'alternative'; node: string } // another move the book gives
  | { kind: 'refuted'; node: string; line: string[] } // a move the book marks as wrong, with its refutation
  | { kind: 'mate' } // a different mate
  | { kind: 'engine'; score: Score; reply?: string } // as good as the best, by the engine
  | { kind: 'wrong'; best?: string; score?: Score } // worse: the engine's best move (UCI) if known

export interface Move {
  from: string
  to: string
  promotion?: string
}

export function uciOf(m: Move): string {
  return m.from + m.to + (m.promotion ?? '')
}

/** The position after a move, or null if it's not legal (pawns reaching the end become queens). */
export function play(fen: string, m: Move): { fen: string; san: string; uci: string; mate: boolean } | null {
  const game = new Chess(fen)
  try {
    const move = game.move({ from: m.from, to: m.to, promotion: m.promotion ?? 'q' })
    return { fen: game.fen(), san: move.san, uci: move.lan, mate: game.isCheckmate() }
  } catch {
    return null
  }
}

/** The book's main line from a node: its moves, main continuation first. */
export function mainLine(tree: BookTree, from: string): MoveNode[] {
  const out: MoveNode[] = []
  let node = tree.get(from)
  while (node?.children.length) {
    node = tree.get(node.children[0])
    if (node) out.push(node)
  }
  return out
}

/** How many moves the solver makes in the book's main line from a node (its own moves, not the replies). */
export function solverMoves(tree: BookTree, from: string): number {
  return Math.ceil(mainLine(tree, from).length / 2)
}

/** True if the book's main line from a node ends in mate. */
export function endsInMate(tree: BookTree, from: string): boolean {
  const line = mainLine(tree, from)
  const last = line[line.length - 1]
  return !!last && new Chess(last.fen).isCheckmate()
}

const REFUTED_NAGS = [2, 4] // "?" and "??"

/**
 * Judges the reader's move in ``fen``. ``node`` is where the book's solution stands (undefined once
 * the reader has left it), ``mateLine`` whether the book's line is a mate.
 */
export async function judge(
  fen: string,
  move: Move,
  tree: BookTree,
  node: string | undefined,
  mateLine: boolean,
  engine: EngineLike | null,
): Promise<Verdict> {
  const after = play(fen, move)
  if (!after) return { kind: 'wrong' }
  const here = node ? tree.get(node) : undefined
  if (here) {
    const children = here.children.map((id) => tree.get(id)!).filter(Boolean)
    const hit = children.find((c) => c.uci === after.uci)
    if (hit && hit === children[0]) return { kind: 'book', node: hit.id }
    if (hit && hit.nags.some((n) => REFUTED_NAGS.includes(n))) {
      return { kind: 'refuted', node: hit.id, line: mainLine(tree, hit.id).map((n) => n.san ?? '') }
    }
    if (hit) return { kind: 'alternative', node: hit.id }
  }
  if (after.mate) return { kind: 'mate' }
  if (mateLine && !engine) return { kind: 'wrong' }
  if (!engine) return { kind: 'wrong' }

  // The engine: the best this side can get here, and what the reader's move keeps of it.
  const best = (await engine.analyse(fen, { movetime: JUDGE_MS }))[0]
  const answer = (await engine.analyse(after.fen, { movetime: JUDGE_MS }))[0]
  if (!best || !answer) return { kind: 'wrong' }
  const kept = flip(answer.score) // the reader's side
  if (isAsGood(best.score, kept)) return { kind: 'engine', score: kept, reply: answer.pv[0] }
  return { kind: 'wrong', best: best.pv[0], score: kept }
}

/**
 * True if a move that keeps ``kept`` is as good as the best move's ``best`` (both for the side
 * moving): within 0.3 pawns, both clearly winning, or a mate at most one move slower.
 */
export function isAsGood(best: Score, kept: Score): boolean {
  if (best.mate !== undefined && best.mate > 0) return kept.mate !== undefined && kept.mate > 0 && kept.mate <= best.mate + MATE_SLACK
  const b = scoreValue(best)
  const k = scoreValue(kept)
  if (b >= DECISIVE_CP && k >= DECISIVE_CP) return true
  return b - k <= TOLERANCE_CP
}

/** The move a hint points at: the book's next move, else the engine's best. */
export async function nextMove(
  fen: string,
  tree: BookTree,
  node: string | undefined,
  engine: EngineLike | null,
): Promise<Move | null> {
  const main = node ? tree.get(tree.get(node)?.children[0] ?? '') : undefined
  const uci = main?.uci ?? (engine ? (await engine.analyse(fen, { movetime: JUDGE_MS }))[0]?.pv[0] : undefined)
  return uci ? { from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] } : null
}
