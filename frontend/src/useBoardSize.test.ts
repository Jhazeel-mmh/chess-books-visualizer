import { describe, expect, it } from 'vitest'
import { boardSide, MIN_BOARD } from './useBoardSize'

describe('board size', () => {
  it('fits the room: the whole board stays on screen', () => {
    expect(boardSide(null, 440, 300)).toBe(300) // a short screen limits it
    expect(boardSide(null, 360, 900)).toBe(360) // a narrow panel limits it
  })
  it('keeps the reader\'s size while it fits', () => {
    expect(boardSide(320, 440, 700)).toBe(320)
    expect(boardSide(600, 440, 700)).toBe(440)
  })
  it('leaves room for the moves until the reader resizes it, and can then grow to the full room', () => {
    expect(boardSide(null, 600, 500, 380)).toBe(380)
    expect(boardSide(460, 600, 500, 380)).toBe(460)
    expect(boardSide(900, 600, 500, 380)).toBe(500)
  })
  it('never gets too small to use', () => {
    expect(boardSide(50, 440, 700)).toBe(MIN_BOARD)
    expect(boardSide(null, 120, 100)).toBe(MIN_BOARD)
  })
})
