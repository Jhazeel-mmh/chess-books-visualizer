import { describe, expect, it } from 'vitest'
import { exploreMove, isPlayable, lineMoves } from './explore'
import { lineNumbers } from './notation'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const PAWNS = '8/pp3ppp/2p5/3p4/3P4/2N5/PP3PPP/8 w - - 0 1' // a pawn structure: no kings

describe('explore', () => {
  it('plays a legal position by the rules', () => {
    expect(isPlayable(START)).toBe(true)
    expect(exploreMove(START, 'g1', 'f3')?.label).toBe('Nf3')
    expect(exploreMove(START, 'g1', 'g3')).toBeNull()
  })

  it('moves pieces freely on an illustration', () => {
    expect(isPlayable(PAWNS)).toBe(false)
    const m = exploreMove(PAWNS, 'c3', 'd5')!
    expect(m.label).toBe('Nc3–d5')
    expect(m.fen.split(' ')[0]).toBe('8/pp3ppp/2p5/3N4/3P4/8/PP3PPP/8')
    expect(exploreMove(m.fen, 'c6', null)!.fen.split(' ')[0]).toBe('8/pp3ppp/8/3N4/3P4/8/PP3PPP/8')
  })
})

describe('a line of moves', () => {
  const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  it('gives each move with the position after it, up to the first one that is not legal', () => {
    const moves = lineMoves(START, ['e2e4', 'e7e5', 'g1f3', 'a1a8'])
    expect(moves.map((m) => m.label)).toEqual(['e4', 'e5', 'Nf3'])
    expect(moves[2].fen.split(' ')[1]).toBe('b')
  })
  it('numbers the moves from the position', () => {
    expect(lineNumbers(START, 4)).toEqual(['1.', '', '2.', ''])
    expect(lineNumbers('4k3/8/8/8/8/8/8/4K3 b - - 0 12', 3)).toEqual(['12…', '13.', ''])
  })
})
