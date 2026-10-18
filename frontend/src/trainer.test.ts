import { Chess } from 'chess.js'
import { describe, expect, it } from 'vitest'
import type { ItemResult, LineNode, SessionPlan, SessionRecord, TrainerRecord } from './api'
import type { EngineLine } from './engine'
import type { EngineLike } from './solve'
import {
  adaptLevel, advance, blockScore, cancelSession, finishSession, goalOf, gradeLine, playOutResult, startSession, streak, treeOf, weekly,
} from './trainer'

/** A book line from a position: SAN moves, the first branch listed is the main one. */
function bookLine(fen: string, branches: string[][]): LineNode[] {
  const nodes: LineNode[] = [{ id: 'r', parent: null, children: [], san: null, uci: null, fen, nags: [], mainline: true }]
  const byKey = new Map<string, LineNode>([['', nodes[0]]])
  branches.forEach((sans) => {
    const game = new Chess(fen)
    let path = ''
    sans.forEach((san) => {
      const parent = byKey.get(path)!
      const m = game.move(san)
      path += `/${m.lan}`
      if (!byKey.has(path)) {
        const n: LineNode = { id: `n${nodes.length}`, parent: parent.id, children: [], san: m.san, uci: m.lan, fen: game.fen(), nags: [], mainline: true }
        parent.children.push(n.id)
        nodes.push(n)
        byKey.set(path, n)
      }
    })
  })
  return nodes
}

// A back-rank mate in one.
const tree = treeOf(bookLine('6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1', [['Ra8#']]))
const noEngine: EngineLike | null = null

describe('grading a calculated line', () => {
  // 1.Ra6+ and the book gives two king moves: 1...Kd5 2.Rb5+ (main) and 1...Ke7 2.Rb7+.
  const start = '8/8/4k3/8/8/8/1R6/R5K1 w - - 0 1'
  const t2 = treeOf(bookLine(start, [['Ra6+', 'Kd5', 'Rb5+'], ['Ra6+', 'Ke7', 'Rb7+']]))

  it('takes the whole line, by any branch the book gives', async () => {
    expect((await gradeLine(start, ['a1a6', 'e6d5', 'b2b5'], t2, 'r', noEngine)).result).toBe('full')
    expect((await gradeLine(start, ['a1a6', 'e6e7', 'b2b7'], t2, 'r', noEngine)).result).toBe('full')
  })

  it('gives the first move only when the line stops short', async () => {
    const g = await gradeLine(start, ['a1a6'], t2, 'r', noEngine)
    expect(g.result).toBe('first')
    expect(g.goesOn).toEqual(['Kd5', 'Rb5+'])
  })

  it('flags a defence the reader did not expect', async () => {
    const g = await gradeLine(start, ['a1a6', 'e6f5', 'b2b5'], t2, 'r', noEngine)
    expect(g.result).toBe('first')
    expect(g.missedDefence).toBe('Kd5')
  })

  it('flags a later move that differs from the book', async () => {
    const g = await gradeLine(start, ['a1a6', 'e6d5', 'b2d2'], t2, 'r', noEngine)
    expect(g.result).toBe('first')
    expect(g.bookMove).toBe('Rb5+')
  })

  it('counts any line that ends in mate', async () => {
    expect((await gradeLine('6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1', ['a1a8'], tree, 'r', noEngine)).result).toBe('full')
  })

  it('is wrong with a wrong first move, or none', async () => {
    expect((await gradeLine(start, ['b2b7'], t2, 'r', noEngine)).result).toBe('wrong')
    expect((await gradeLine(start, [], t2, 'r', noEngine)).result).toBe('wrong')
  })

  /** An engine that sees White winning by 9 everywhere, except in the positions given. */
  const engineWith = (special: Record<string, number> = {}): EngineLike => ({
    async analyse(fen: string): Promise<EngineLine[]> {
      const white = fen in special ? special[fen] : 900
      return [{ depth: 20, score: { cp: fen.split(' ')[1] === 'w' ? white : -white }, pv: ['a1a6'] }]
    },
  })
  const after = (...ucis: string[]) => {
    const game = new Chess(start)
    for (const u of ucis) game.move({ from: u.slice(0, 2), to: u.slice(2, 4) })
    return game.fen()
  }

  it("takes a later move that the engine finds as good as the book's", async () => {
    const g = await gradeLine(start, ['a1a6', 'e6d5', 'b2b6'], t2, 'r', engineWith())
    expect(g.result).toBe('full')
    expect(g.byEngine).toBe(1)
  })

  it('still marks a later move that throws the win away', async () => {
    const bad = after('a1a6', 'e6d5', 'b2h2')
    const g = await gradeLine(start, ['a1a6', 'e6d5', 'b2h2'], t2, 'r', engineWith({ [bad]: 0 }))
    expect(g.result).toBe('first')
    expect(g.bookMove).toBe('Rb5+')
  })

  it('takes a reply the book does not give when it defends as well', async () => {
    const g = await gradeLine(start, ['a1a6', 'e6f5', 'b2b5'], t2, 'r', engineWith())
    expect(g.result).toBe('full')
    expect(g.missedDefence).toBeUndefined()
  })

  it('flags a reply that is weaker than the best defence', async () => {
    const weak = after('a1a6', 'e6f5')
    const g = await gradeLine(start, ['a1a6', 'e6f5', 'b2b5'], t2, 'r', engineWith({ [weak]: 5000 }))
    expect(g.result).toBe('first')
    expect(g.missedDefence).toBe('Kd5')
  })

  it("wants the line to the end, also off the book's path", async () => {
    const g = await gradeLine(start, ['b2b6'], t2, 'r', engineWith())
    expect(g.result).toBe('first')
    expect(g.short).toBe(true)
  })

  it('lets the engine approve another first move', async () => {
    const engine: EngineLike = {
      async analyse(fen: string): Promise<EngineLine[]> {
        // Both the best line and the reader's move keep a won position.
        return [{ depth: 20, score: fen === start ? { cp: 900 } : { cp: -900 }, pv: ['a1a6'] }]
      },
    }
    const g = await gradeLine(start, ['b2b6', 'e6d5', 'a1a5'], t2, 'r', engine)
    expect(g.first.kind).toBe('engine')
    expect(g.result).toBe('full')
  })
})

describe('endgames played out', () => {
  it('sets the goal from the engine', () => {
    expect(goalOf({ cp: 400 })).toBe('win')
    expect(goalOf({ mate: 12 })).toBe('win')
    expect(goalOf({ cp: 40 })).toBe('draw')
    expect(goalOf({ cp: -250 })).toBe('draw')
  })
  it('judges the result against the goal', () => {
    expect(playOutResult('win', { kind: 'mate', readerWon: true })).toBe('met')
    expect(playOutResult('win', { kind: 'draw' })).toBe('failed')
    expect(playOutResult('win', { kind: 'limit', score: { cp: 500 } })).toBe('partial')
    expect(playOutResult('draw', { kind: 'draw' })).toBe('met')
    expect(playOutResult('draw', { kind: 'limit', score: { cp: -50 } })).toBe('met')
    expect(playOutResult('draw', { kind: 'mate', readerWon: false })).toBe('failed')
    expect(playOutResult('draw', { kind: 'resigned' })).toBe('failed')
  })
})

describe('difficulty follows the results (60–80% right)', () => {
  it('goes up, down, or stays', () => {
    expect(adaptLevel(3, ['full', 'full', 'full'])).toBe(3.25)
    expect(adaptLevel(3, ['wrong', 'first', 'wrong'])).toBe(2.75)
    expect(adaptLevel(3, ['full', 'first', 'wrong', 'full'])).toBe(3) // 62%
    expect(adaptLevel(3, ['full'])).toBe(3)
    expect(adaptLevel(1, ['wrong', 'wrong'])).toBe(1)
  })
})

const EMPTY: TrainerRecord = {
  settings: { minutes: 50, rating: 1800, focus: null }, level: null, roles: {}, positions: {},
  reading: { book: null, at: {} }, games: { current: null, at: {} }, sources: {}, sessions: [], current: null,
}

describe('a session in the record', () => {
  const plan: SessionPlan = {
    id: 's1', test: false, level: 3, planned: 45,
    blocks: [
      { kind: 'calculation', minutes: 18, items: [{ book: 'a', key: 'k1' }, { book: 'a', key: 'k2' }] as never },
      { kind: 'reading', minutes: 9, items: [{ book: 'b' }] as never },
    ],
  }
  it('moves on item by item, block by block, and keeps what was done', () => {
    let r = startSession(EMPTY, plan, '2026-10-15T10:00:00Z')
    const calc = (key: string, result: 'full' | 'wrong'): ItemResult => ({ kind: 'calculation', book: 'a', key, result, ms: 1000, line: [] })
    r = advance(r, calc('k1', 'full'), '2026-10-15T10:06:00Z')
    expect([r.current!.block, r.current!.item]).toEqual([0, 1])
    r = advance(r, calc('k2', 'wrong'), '2026-10-15T10:12:00Z')
    expect([r.current!.block, r.current!.item]).toEqual([1, 0])
    expect(r.positions['a:k2']).toEqual([{ at: '2026-10-15T10:12:00Z', result: 'wrong' }])
    r = advance(r, { kind: 'reading', book: 'b', from: 10, to: 14, ms: 1 }, '2026-10-15T10:20:00Z')
    expect(r.reading).toEqual({ book: 'b', at: { b: 14 } })
    r = finishSession(r, 7, 'Check every capture', '2026-10-15T10:45:00Z')
    expect(r.current).toBeNull()
    expect(r.sessions[0]).toMatchObject({ id: 's1', focus: 7, note: 'Check every capture', ms: 45 * 60000 })
    expect(r.level).toBe(2.75) // one right, one wrong: 50% is below the target, so easier next time
  })
})

describe('cancelling a session', () => {
  it('drops it from the record but keeps what was already done', () => {
    const plan: SessionPlan = { id: 's2', test: false, level: 3, planned: 18, blocks: [{ kind: 'calculation', minutes: 18, items: [{ book: 'a', key: 'k1' }, { book: 'a', key: 'k2' }] as never }] }
    let r = startSession(EMPTY, plan, '2026-10-17T10:00:00Z')
    r = advance(r, { kind: 'calculation', book: 'a', key: 'k1', result: 'full', ms: 1, line: [] }, '2026-10-17T10:05:00Z')
    r = cancelSession(r)
    expect(r.current).toBeNull()
    expect(r.sessions).toEqual([])
    expect(r.level).toBeNull()
    expect(r.positions['a:k1']).toHaveLength(1)
  })
})

describe('history', () => {
  const session = (finished: string, results: ItemResult[][] = []): SessionRecord => ({
    id: finished, test: false, started: finished, finished, ms: 50 * 60000, results, kinds: [], focus: 8, note: '',
  })
  it('counts the streak of days', () => {
    const s = ['2026-10-13T09:00:00Z', '2026-10-14T09:00:00Z', '2026-10-15T09:00:00Z'].map((d) => session(d))
    expect(streak(s, new Date('2026-10-15T20:00:00Z'))).toBe(3)
    expect(streak(s.slice(0, 2), new Date('2026-10-15T08:00:00Z'))).toBe(2) // today's still to come
    expect(streak(s.slice(0, 1), new Date('2026-10-15T08:00:00Z'))).toBe(0)
  })
  it('sums up the weeks', () => {
    const results: ItemResult[][] = [[
      { kind: 'calculation', book: 'a', key: '1', result: 'full', ms: 1, line: [] },
      { kind: 'calculation', book: 'a', key: '2', result: 'first', ms: 1, line: [] },
    ], [{ kind: 'reading', book: 'b', from: 3, to: 9, ms: 1 }], [{ kind: 'guess', book: 'c', game: 'g', same: 3, good: 2, total: 10, at: 30, ms: 1 }]]
    const [week] = weekly([session('2026-10-14T09:00:00Z', results)], new Date('2026-10-15T09:00:00Z'))
    expect(week).toMatchObject({ week: '2026-10-12', sessions: 1, minutes: 50, pages: 6 })
    expect(week.scores).toEqual({ calculation: 0.75, endgame: null, guess: 0.5 })
    expect(blockScore([])).toBeNull()
  })
})
