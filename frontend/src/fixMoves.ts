/**
 * Fixing moves on a book's pages: the reader entered a move the app could not read (or removed a
 * false one). Here: where a fix starts from, and moves typed in either language.
 */

import { Chess } from 'chess.js'
import type { PageMark } from './api'

type Rect = [number, number, number, number]

/** Spanish piece letters (Rey, Dama, Torre, Alfil, Caballo) in English. */
const SPANISH: Record<string, string> = { R: 'K', D: 'Q', T: 'R', A: 'B', C: 'N' }

/** A move typed as in the book ("Nf3", "Cf3", "0-0", "exd5!?"), or null if it is not legal here. */
export function typedMove(fen: string, text: string): { san: string; uci: string; fen: string } | null {
  const clean = text.trim().replace(/[!?+#]+$/g, '').replace(/0/g, 'O').replace(/[–—]/g, '-')
  if (!clean) return null
  const spanish = clean.replace(/^[RDTAC]/, (c) => SPANISH[c]).replace(/=([DTAC])$/, (_, c) => `=${SPANISH[c]}`)
  for (const san of [clean, spanish]) {
    const game = new Chess(fen)
    try {
      const m = game.move(san, { strict: false })
      return { san: m.san, uci: m.from + m.to + (m.promotion ?? ''), fen: game.fen() }
    } catch {
      // not this notation
    }
  }
  return null
}

const overlaps = (a: Rect, b: Rect) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3]

/**
 * The linked move printed last before ``box`` on the page (top to bottom, left to right): the fix
 * most likely follows it. Moves inside the box are the ones being fixed and do not count.
 */
export function moveBefore(marks: PageMark[], box: Rect): string | null {
  const midY = (box[1] + box[3]) / 2
  let best: { key: [number, number]; id: string } | null = null
  for (const m of marks) {
    if (m.kind !== 'move') continue
    for (const r of m.rects) {
      if (overlaps(r, box)) continue
      const cy = (r[1] + r[3]) / 2
      const sameLine = r[1] < midY && midY < r[3]
      const before = r[3] <= box[1] + 2 || (sameLine && r[2] <= box[0] + 1)
      const key: [number, number] = [sameLine ? midY : cy, r[2]]
      if (before && (!best || key[0] > best.key[0] || (key[0] === best.key[0] && key[1] > best.key[1]))) best = { key, id: m.id }
    }
  }
  return best?.id ?? null
}
