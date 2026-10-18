import { useCallback, useLayoutEffect, useState, type RefObject } from 'react'
import { load, save } from './storage'

/** The smallest board worth showing, in pixels. */
export const MIN_BOARD = 200
/** The least room kept under the board: its size buttons and the navigation. */
const BELOW = 110
/** Until the reader resizes it, also room for the engine's line and some of the moves. */
const BELOW_AT_FIRST = 230

/**
 * The board's side: the size the reader chose (or, until then, ``preferred``), as far as the room
 * allows, so the whole board is always on screen.
 */
export function boardSide(chosen: number | null, width: number, height: number, preferred = height): number {
  const room = Math.max(MIN_BOARD, Math.floor(Math.min(width, height)))
  const start = Math.max(MIN_BOARD, Math.floor(Math.min(width, preferred)))
  return Math.max(MIN_BOARD, Math.min(chosen ?? start, room))
}

/**
 * Measures the room a board has in ``slot`` (its width, and the height left on screen below its
 * top) and gives the board's side. The reader's choice is remembered under ``key``.
 */
export function useBoardSize(slot: RefObject<HTMLElement | null>, key = 'boardSize') {
  const [chosen, setChosen] = useState<number | null>(() => load<number | null>(key, null))
  const [room, setRoom] = useState({ width: 420, height: 420, preferred: 420 })

  useLayoutEffect(() => {
    const el = slot.current
    if (!el) return
    const measure = () => {
      const below = window.innerHeight - Math.max(0, el.getBoundingClientRect().top)
      setRoom({ width: el.clientWidth, height: below - BELOW, preferred: below - BELOW_AT_FIRST })
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    window.addEventListener('resize', measure)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [slot])

  const choose = useCallback(
    (px: number | null) => {
      setChosen(px)
      save(key, px)
    },
    [key],
  )
  const fits = boardSide(null, room.width, room.height)
  return { size: boardSide(chosen, room.width, room.height, room.preferred), fits, chosen, choose }
}
