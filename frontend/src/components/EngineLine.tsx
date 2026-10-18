import { Fragment, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { engine, flip, formatScore, type EngineLine as Line } from '../engine'
import { isPlayable, lineMoves, type ExploreMove } from '../explore'
import { displaySan, lineNumbers } from '../notation'

interface Props {
  fen: string
  /** How moves are shown: the reader's language, or figurines. */
  lang?: string
  figurines?: boolean
  /** Clicking a move of the line plays it (and the moves before it) on the board. */
  onPlay?: (moves: ExploreMove[]) => void
}

/** The engine's evaluation and best line for a position, while it is shown. */
export function EngineLine(props: Props) {
  const { t } = useTranslation()
  if (!isPlayable(props.fen)) return <p className="engine hint">{t('engine.notLegal')}</p>
  return <Analysis {...props} />
}

function Analysis({ fen, lang = 'en', figurines = false, onPlay }: Props) {
  const { t } = useTranslation()
  const [state, setState] = useState<{ fen: string; lines: Line[]; failed: boolean }>({ fen, lines: [], failed: false })
  useEffect(() => {
    let alive = true
    const show = (lines: Line[]) => alive && lines.length > 0 && setState({ fen, lines, failed: false })
    engine.analyse(fen, { movetime: 5000, onUpdate: show }).then(show, () => alive && setState({ fen, lines: [], failed: true }))
    return () => {
      alive = false
      engine.stop()
    }
  }, [fen])

  if (state.failed) return <p className="engine hint">{t('engine.unavailable')}</p>
  const line = state.fen === fen ? state.lines[0] : undefined
  if (!line) return <p className="engine hint">{t('engine.thinking')}</p>
  const white = fen.split(' ')[1] === 'w' ? line.score : flip(line.score)
  const moves = lineMoves(fen, line.pv, 10)
  const numbers = lineNumbers(fen, moves.length)
  const value = white.mate !== undefined ? (white.mate >= 0 ? 1 : -1) : Math.max(-1, Math.min(1, (white.cp ?? 0) / 600))
  return (
    <div className="engine">
      <span className="engine-score" title={t('engine.depth', { depth: line.depth })}>{formatScore(white)}</span>
      <span className="engine-bar" aria-hidden="true">
        <span style={{ width: `${50 + value * 50}%` }} />
      </span>
      <span className="engine-line">
        {moves.map((m, i) => (
          <Fragment key={i}>
            {numbers[i] && <span className="move-number">{numbers[i]}</span>}
            {onPlay ? (
              <button type="button" className="move" onClick={() => onPlay(moves.slice(0, i + 1))} title={t('engine.playTo')}>
                {displaySan(m.label, lang, figurines)}
              </button>
            ) : (
              <span>{displaySan(m.label, lang, figurines)}</span>
            )}{' '}
          </Fragment>
        ))}
      </span>
    </div>
  )
}
