import { describe, expect, it } from 'vitest'
import { flip, parseInfo, scoreValue } from './engine'

describe('engine output', () => {
  it('reads a scored line', () => {
    const line = 'info depth 18 seldepth 22 multipv 2 score cp 712 nodes 304494 nps 608988 time 500 pv g2g4 f7f6 g4g5'
    expect(parseInfo(line)).toEqual({ depth: 18, multipv: 2, score: { cp: 712 }, pv: ['g2g4', 'f7f6', 'g4g5'] })
  })

  it('reads mates and skips bounds and lines without moves', () => {
    expect(parseInfo('info depth 5 multipv 1 score mate 1 nodes 10 pv d1d8')?.score).toEqual({ mate: 1 })
    expect(parseInfo('info depth 5 score cp 30 lowerbound nodes 10 pv e2e4')).toBeNull()
    expect(parseInfo('info string NNUE evaluation using nn-1.nnue')).toBeNull()
  })

  it('orders scores, quicker mates first', () => {
    expect(scoreValue({ mate: 1 })).toBeGreaterThan(scoreValue({ mate: 3 }))
    expect(scoreValue({ mate: 3 })).toBeGreaterThan(scoreValue({ cp: 900 }))
    expect(scoreValue({ mate: -2 })).toBeLessThan(scoreValue({ cp: -900 }))
    expect(flip({ mate: 2 })).toEqual({ mate: -2 })
    expect(flip({ cp: 50 })).toEqual({ cp: -50 })
  })
})
