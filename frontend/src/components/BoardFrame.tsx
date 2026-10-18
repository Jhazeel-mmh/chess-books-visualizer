import { useRef, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { MIN_BOARD, useBoardSize } from '../useBoardSize'

const STEP = 40

/**
 * Holds a board at a size that always fits on screen, with a corner handle to resize it and
 * − / + / fit buttons. The chosen size is remembered under ``sizeKey``.
 */
export function BoardFrame({ children, sizeKey = 'boardSize' }: { children: ReactNode; sizeKey?: string }) {
  const { t } = useTranslation()
  const slot = useRef<HTMLDivElement>(null)
  const { size, fits, choose } = useBoardSize(slot, sizeKey)

  const startDrag = (e: ReactPointerEvent<HTMLElement>) => {
    e.preventDefault()
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)
    const start = { x: e.clientX, y: e.clientY, size }
    const move = (ev: PointerEvent) => {
      const grow = Math.max(ev.clientX - start.x, ev.clientY - start.y)
      choose(Math.round(Math.max(MIN_BOARD, Math.min(fits, start.size + grow))))
    }
    const end = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', end)
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
  }

  return (
    <div className="board-slot" ref={slot}>
      <div className="board" style={{ width: size, height: size }}>
        {children}
        <span
          className="board-resize"
          role="separator"
          aria-label={t('board.resize')}
          title={t('board.resize')}
          onPointerDown={startDrag}
        />
      </div>
      <div className="board-size" role="group" aria-label={t('board.size')}>
        <button type="button" onClick={() => choose(Math.max(MIN_BOARD, size - STEP))} disabled={size <= MIN_BOARD} title={t('board.smaller')} aria-label={t('board.smaller')}>−</button>
        <button type="button" onClick={() => choose(fits)} title={t('board.fit')} aria-label={t('board.fit')}>⤢</button>
        <button type="button" onClick={() => choose(Math.min(fits, size + STEP))} disabled={size >= fits} title={t('board.bigger')} aria-label={t('board.bigger')}>+</button>
      </div>
    </div>
  )
}
