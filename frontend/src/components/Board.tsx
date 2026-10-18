import { useState, type CSSProperties } from 'react'
import { Chessboard, defaultArrowOptions } from 'react-chessboard'
import type { PositionNotes } from '../userData'

export interface BoardArrow {
  from: string
  to: string
  color?: string
}

interface Props {
  id: string
  fen: string
  orientation: 'white' | 'black'
  /** Slide pieces into place (for one move forward or back); otherwise the new position just appears. */
  animate: boolean
  /** Lets the reader move pieces by dragging or by clicking two squares. Returns whether the move was taken. */
  onMove?: (from: string, to: string | null) => boolean
  /** Whose pieces may be picked up ("w", "b"), or any piece if not given. */
  mover?: 'w' | 'b'
  /** Pieces may be dragged off the board (to remove them). */
  offBoard?: boolean
  /** The reader's own arrows and circles on this position, and how to change them. */
  notes?: PositionNotes
  onNotes?: (notes: PositionNotes) => void
  /** Arrows and square highlights the app shows (hints, the solution), not saved. */
  arrows?: BoardArrow[]
  highlights?: Record<string, CSSProperties>
}

const ARROW_COLOR = 'rgba(21, 120, 27, 0.85)'
const CIRCLE: CSSProperties = {
  background: 'radial-gradient(circle, transparent 56%, rgba(21, 120, 27, 0.85) 58%, rgba(21, 120, 27, 0.85) 66%, transparent 68%)',
}
const SELECTED: CSSProperties = { background: 'rgba(242, 201, 76, 0.55)' }

/** The chessboard used in both modes: reading (with exploring) and solving. */
export function Board(props: Props) {
  const { fen, onMove, mover, notes, onNotes } = props
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedIn, setSelectedIn] = useState(fen)
  // A new position clears a half-made click-click move.
  if (selectedIn !== fen) {
    setSelectedIn(fen)
    setSelected(null)
  }

  const isMovable = (piece: string | undefined) => !!onMove && !!piece && (!mover || piece[0] === mover)

  const styles: Record<string, CSSProperties> = { ...props.highlights }
  for (const sq of notes?.circles ?? []) styles[sq] = { ...styles[sq], ...CIRCLE }
  if (selected) styles[selected] = { ...styles[selected], ...SELECTED }

  const arrows = [
    ...(notes?.arrows ?? []).map(([from, to, color]) => ({ startSquare: from, endSquare: to, color })),
    ...(props.arrows ?? []).map((a) => ({ startSquare: a.from, endSquare: a.to, color: a.color ?? 'rgba(242, 160, 30, 0.9)' })),
  ]

  return (
    <Chessboard
      options={{
        id: props.id,
        position: fen,
        boardOrientation: props.orientation,
        showAnimations: props.animate,
        animationDurationInMs: 150,
        allowDragging: !!onMove,
        allowDragOffBoard: !!props.offBoard,
        canDragPiece: ({ piece }) => isMovable(piece.pieceType),
        onPieceDrop: ({ sourceSquare, targetSquare }) => {
          setSelected(null)
          return onMove ? onMove(sourceSquare, targetSquare) : false
        },
        onSquareClick: ({ piece, square }) => {
          if (!onMove) return
          const movable = !!piece && isMovable(piece.pieceType)
          if (selected && selected !== square) {
            // Second click: move there; if that's no move, a click on another own piece picks it instead.
            if (onMove(selected, square)) setSelected(null)
            else setSelected(movable ? square : null)
          } else {
            setSelected(movable && square !== selected ? square : null)
          }
        },
        allowDrawingArrows: !!onNotes,
        arrows,
        arrowOptions: ARROWS,
        clearArrowsOnPositionChange: true,
        onArrowsChange: ({ arrows: drawn }) => {
          if (!onNotes || !drawn.length) return
          const saved = notes?.arrows ?? []
          const added = drawn
            .filter((a) => !saved.some(([f, t]) => f === a.startSquare && t === a.endSquare))
            .map((a): [string, string, string] => [a.startSquare, a.endSquare, a.color])
          if (added.length) onNotes({ arrows: [...saved, ...added], circles: notes?.circles ?? [] })
        },
        onSquareRightClick: ({ square }) => {
          if (!onNotes) return
          const circles = notes?.circles ?? []
          onNotes({
            arrows: notes?.arrows ?? [],
            circles: circles.includes(square) ? circles.filter((c) => c !== square) : [...circles, square],
          })
        },
        squareStyles: styles,
        darkSquareStyle: { backgroundColor: 'var(--square-dark)' },
        lightSquareStyle: { backgroundColor: 'var(--square-light)' },
      }}
    />
  )
}

const ARROWS = {
  ...defaultArrowOptions,
  colors: { ...defaultArrowOptions.colors, default: ARROW_COLOR },
  color: ARROW_COLOR,
}
