import { describe, expect, it } from 'vitest'
import type { MoveNode } from './api'
import type { EngineLine } from './engine'
import { endsInMate, isAsGood, judge, nextMove, play, solverMoves, type BookTree, type EngineLike } from './solve'

const START = '6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1' // 1.Rd8# mates; 1.Rd7 doesn't

function node(id: string, parent: string | null, uci: string | null, fen: string, children: string[] = [], nags: number[] = []): MoveNode {
  return { id, parent, children, san: uci, uci, fen, nags, mainline: true, refs: [] }
}

/** A book that gives 1.Rd7 (main), 1.Re1 (another move) and 1.Rc1? (refuted by 1...Kf8). */
function book(): BookTree {
  const after = (uci: string) => play(START, { from: uci.slice(0, 2), to: uci.slice(2, 4) })!.fen
  const rc1 = after('d1c1')
  const nodes = [
    node('r', null, null, START, ['a', 'b', 'c']),
    node('a', 'r', 'd1d7', after('d1d7')),
    node('b', 'r', 'd1e1', after('d1e1')),
    node('c', 'r', 'd1c1', rc1, ['c1'], [2]),
    node('c1', 'c', 'g8f8', play(rc1, { from: 'g8', to: 'f8' })!.fen),
  ]
  return new Map(nodes.map((n) => [n.id, n]))
}

/** An engine that answers from a table: the score for the side to move in each position. */
function fakeEngine(scores: Record<string, { cp?: number; mate?: number; pv?: string[] }>): EngineLike {
  return {
    async analyse(fen: string): Promise<EngineLine[]> {
      const s = scores[fen.split(' ').slice(0, 2).join(' ')]
      return s ? [{ depth: 20, score: s.mate !== undefined ? { mate: s.mate } : { cp: s.cp }, pv: s.pv ?? [] }] : []
    },
  }
}

const key = (fen: string) => fen.split(' ').slice(0, 2).join(' ')

describe('judging a move', () => {
  it('knows the book', async () => {
    const tree = book()
    expect(await judge(START, { from: 'd1', to: 'd7' }, tree, 'r', false, null)).toEqual({ kind: 'book', node: 'a' })
    expect(await judge(START, { from: 'd1', to: 'e1' }, tree, 'r', false, null)).toEqual({ kind: 'alternative', node: 'b' })
    expect(await judge(START, { from: 'd1', to: 'c1' }, tree, 'r', false, null)).toEqual({ kind: 'refuted', node: 'c', line: ['g8f8'] })
  })

  it('takes any mate', async () => {
    expect(await judge(START, { from: 'd1', to: 'd8' }, book(), 'r', true, null)).toEqual({ kind: 'mate' })
  })

  it('asks the engine about other moves', async () => {
    const after = play(START, { from: 'd1', to: 'b1' })!.fen
    const equal = fakeEngine({ [key(START)]: { cp: 120, pv: ['d1d7'] }, [key(after)]: { cp: -100, pv: ['h7h6'] } })
    expect(await judge(START, { from: 'd1', to: 'b1' }, book(), 'r', false, equal)).toEqual({ kind: 'engine', score: { cp: 100 }, reply: 'h7h6' })
    const worse = fakeEngine({ [key(START)]: { cp: 120, pv: ['d1d7'] }, [key(after)]: { cp: 50 } })
    expect(await judge(START, { from: 'd1', to: 'b1' }, book(), 'r', false, worse)).toEqual({ kind: 'wrong', best: 'd1d7', score: { cp: -50 } })
  })

  it('compares results the way a solver would', () => {
    expect(isAsGood({ mate: 2 }, { mate: 2 })).toBe(true)
    expect(isAsGood({ mate: 2 }, { mate: 3 })).toBe(true) // one move slower: still the idea
    expect(isAsGood({ mate: 2 }, { mate: 4 })).toBe(false) // much slower: not the solution
    expect(isAsGood({ cp: 900 }, { cp: 350 })).toBe(true) // still clearly winning
    expect(isAsGood({ cp: 40 }, { cp: -20 })).toBe(false)
  })
})

describe('the book line', () => {
  it('counts the solver moves and the mate', async () => {
    const tree = book()
    expect(solverMoves(tree, 'r')).toBe(1)
    expect(endsInMate(tree, 'r')).toBe(false)
    expect(await nextMove(START, tree, 'r', null)).toEqual({ from: 'd1', to: 'd7', promotion: undefined })
  })
})
