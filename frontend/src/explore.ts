/**
 * Moving pieces on the reader's board to try ideas ("explore").
 *
 * A legal position is played by the rules (chess.js). An illustration (a pawn structure with no
 * kings, two half-boards, two kings of one colour) is not a position chess.js accepts, so there
 * pieces simply move wherever they are dragged, capture what they land on, or leave the board.
 */

import { Chess, validateFen } from 'chess.js'

export interface ExploreMove {
  /** Position after the move. */
  fen: string
  /** How the move is shown: SAN when played by the rules ("Nf3"), else "Nb1–c3". */
  label: string
  from: string
  to: string | null
}

/** True if the position can be played by the rules (both kings, nothing impossible). */
export function isPlayable(fen: string): boolean {
  if (!validateFen(fen).ok) return false
  try {
    new Chess(fen)
    return true
  } catch {
    return false
  }
}

/** The move from one square to another by the rules (a pawn reaching the end becomes a queen), or null. */
export function legalMove(fen: string, from: string, to: string): ExploreMove | null {
  const game = new Chess(fen)
  try {
    const move = game.move({ from, to, promotion: 'q' })
    return { fen: game.fen(), label: move.san, from, to }
  } catch {
    return null
  }
}

const FILES = 'abcdefgh'

function squares(placement: string): (string | null)[] {
  const out: (string | null)[] = []
  for (const row of placement.split('/')) {
    for (const ch of row) {
      if (/\d/.test(ch)) out.push(...Array<null>(Number(ch)).fill(null))
      else out.push(ch)
    }
  }
  return out
}

function placementOf(board: (string | null)[]): string {
  const rows: string[] = []
  for (let r = 0; r < 8; r++) {
    let row = ''
    let empty = 0
    for (const piece of board.slice(r * 8, r * 8 + 8)) {
      if (piece) {
        row += (empty || '') + piece
        empty = 0
      } else empty++
    }
    rows.push(row + (empty || ''))
  }
  return rows.join('/')
}

function index(square: string): number {
  return (8 - Number(square[1])) * 8 + FILES.indexOf(square[0])
}

/** Moves a piece anywhere (or off the board when ``to`` is null), ignoring the rules. */
export function freeMove(fen: string, from: string, to: string | null): ExploreMove | null {
  const [placement, side = 'w'] = fen.split(' ')
  const board = squares(placement)
  const piece = board[index(from)]
  if (!piece || from === to) return null
  board[index(from)] = null
  if (to) board[index(to)] = piece
  const name = piece.toUpperCase() === 'P' ? '' : piece.toUpperCase()
  const label = to ? `${name}${from}–${to}` : `${name}${from}×`
  return { fen: `${placementOf(board)} ${side === 'w' ? 'b' : 'w'} - - 0 1`, label, from, to }
}

/** A move on the explore board: by the rules when the position allows it, freely otherwise. */
export function exploreMove(fen: string, from: string, to: string | null): ExploreMove | null {
  if (isPlayable(fen)) return to ? legalMove(fen, from, to) : null
  return freeMove(fen, from, to)
}

/** The colour of the piece on a square ("w" or "b"), or null. */
export function pieceColor(fen: string, square: string): 'w' | 'b' | null {
  const piece = squares(fen.split(' ')[0])[index(square)]
  return piece ? (piece === piece.toUpperCase() ? 'w' : 'b') : null
}

/** UCI moves ("g1f3") as SAN from a position, as far as they are legal. */
export function sanLine(fen: string, uci: string[], max = 8): string[] {
  return lineMoves(fen, uci, max).map((m) => m.label)
}

/** A line of moves (UCI) from a position, each with the position after it; stops at the first one that isn't legal. */
export function lineMoves(fen: string, uci: string[], max = 12): ExploreMove[] {
  const game = new Chess(fen)
  const out: ExploreMove[] = []
  for (const m of uci.slice(0, max)) {
    try {
      const move = game.move({ from: m.slice(0, 2), to: m.slice(2, 4), promotion: m[4] })
      out.push({ fen: game.fen(), label: move.san, from: move.from, to: move.to })
    } catch {
      break
    }
  }
  return out
}
