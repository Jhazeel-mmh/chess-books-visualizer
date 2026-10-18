import { describe, expect, it } from 'vitest'
import type { PageMark } from './api'
import { moveBefore, typedMove } from './fixMoves'

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

describe('typed moves', () => {
  it('reads English and Spanish letters', () => {
    expect(typedMove(START, 'Nf3')?.uci).toBe('g1f3')
    expect(typedMove(START, 'Cf3')?.uci).toBe('g1f3')
    expect(typedMove(START, 'e4!?')?.san).toBe('e4')
  })
  it('reads castling with zeros and refuses illegal moves', () => {
    const castle = 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1'
    expect(typedMove(castle, '0-0')?.uci).toBe('e1g1')
    expect(typedMove(castle, 'O-O-O')?.uci).toBe('e1c1')
    expect(typedMove(START, 'Nf6')).toBeNull()
    expect(typedMove(START, '')).toBeNull()
  })
  it('takes a Spanish rook (T) and king (R)', () => {
    const fen = '4k3/8/8/8/8/8/8/R3K3 w - - 0 1'
    expect(typedMove(fen, 'Ta8')?.uci).toBe('a1a8')
    expect(typedMove(fen, 'Rd2')?.uci).toBe('e1d2')
  })
})

describe('the move before a box', () => {
  const mark = (id: string, rect: [number, number, number, number]): PageMark => ({ kind: 'move', id, rects: [rect] })
  const marks = [mark('a', [40, 90, 60, 102]), mark('b', [70, 90, 90, 102]), mark('c', [40, 110, 60, 122]), mark('d', [100, 110, 120, 122])]
  it('is the last move printed before it, on its line or above', () => {
    expect(moveBefore(marks, [65, 108, 95, 124])).toBe('c')
    expect(moveBefore(marks, [30, 108, 38, 124])).toBe('b')
    expect(moveBefore(marks, [10, 60, 30, 70])).toBeNull()
  })
  it('skips the move being fixed', () => {
    expect(moveBefore(marks, [98, 108, 122, 124])).toBe('c')
  })
})
