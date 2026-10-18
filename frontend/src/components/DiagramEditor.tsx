import { useState } from 'react'
import { Chessboard } from 'react-chessboard'
import { useTranslation } from 'react-i18next'
import { BoardFrame } from './BoardFrame'

const PALETTE = ['K', 'Q', 'R', 'B', 'N', 'P', 'k', 'q', 'r', 'b', 'n', 'p']
const GLYPH: Record<string, string> = {
  K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘', P: '♙', k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟',
}

interface Props {
  placement: string
  turn: 'w' | 'b'
  /** Squares the recognizer was unsure about (0 = a8 … 63 = h1). */
  uncertain: number[]
  saving: boolean
  onSave: (placement: string, turn: 'w' | 'b') => void
  onCancel: () => void
}

/** Fixes a misread diagram: pick a piece (or the eraser) and click squares. */
export function DiagramEditor({ placement, turn, uncertain, saving, onSave, onCancel }: Props) {
  const { t } = useTranslation()
  const [squares, setSquares] = useState(() => expand(placement))
  const [side, setSide] = useState(turn)
  const [brush, setBrush] = useState('P')

  const paint = (square: string) => {
    const i = index(square)
    setSquares((s) => s.map((v, j) => (j === i ? (v === brush ? '' : brush) : v)))
  }
  const styles = Object.fromEntries(
    uncertain.map((i) => [name(i), { boxShadow: 'inset 0 0 0 3px rgba(230, 126, 34, 0.9)' }]),
  )

  return (
    <div className="diagram-editor">
      <p className="hint">{t('reader.editHint')}</p>
      <BoardFrame sizeKey="boardSize">
        <Chessboard
          options={{
            id: 'diagram-editor',
            position: `${compress(squares)} ${side} - - 0 1`,
            allowDragging: false,
            squareStyles: styles,
            onSquareClick: ({ square }) => paint(square),
            darkSquareStyle: { backgroundColor: 'var(--square-dark)' },
            lightSquareStyle: { backgroundColor: 'var(--square-light)' },
          }}
        />
      </BoardFrame>
      <div className="palette">
        {PALETTE.map((p) => (
          <button key={p} type="button" className={brush === p ? 'active' : ''} onClick={() => setBrush(p)} aria-label={p}>
            {GLYPH[p]}
          </button>
        ))}
        <button type="button" className={brush === '' ? 'active' : ''} onClick={() => setBrush('')}>
          {t('reader.eraser')}
        </button>
      </div>
      <div className="tools">
        <label className="check">
          <input type="radio" checked={side === 'w'} onChange={() => setSide('w')} />
          {t('reader.whiteToMove')}
        </label>
        <label className="check">
          <input type="radio" checked={side === 'b'} onChange={() => setSide('b')} />
          {t('reader.blackToMove')}
        </label>
      </div>
      <div className="tools">
        <button type="button" className="button primary" disabled={saving} onClick={() => onSave(compress(squares), side)}>
          {t('reader.save')}
        </button>
        <button type="button" onClick={onCancel} disabled={saving}>
          {t('reader.cancel')}
        </button>
      </div>
    </div>
  )
}

function expand(placement: string): string[] {
  const out: string[] = []
  for (const ch of placement.replaceAll('/', '')) {
    if (/\d/.test(ch)) out.push(...Array(Number(ch)).fill(''))
    else out.push(ch)
  }
  while (out.length < 64) out.push('')
  return out.slice(0, 64)
}

function compress(squares: string[]): string {
  const rows = []
  for (let r = 0; r < 8; r++) {
    let row = ''
    let empty = 0
    for (const s of squares.slice(r * 8, r * 8 + 8)) {
      if (s) {
        row += (empty || '') + s
        empty = 0
      } else empty++
    }
    rows.push(row + (empty || ''))
  }
  return rows.join('/')
}

const index = (square: string) => (8 - Number(square[1])) * 8 + square.charCodeAt(0) - 97
const name = (i: number) => `${String.fromCharCode(97 + (i % 8))}${8 - Math.floor(i / 8)}`
