import { Chess } from 'chess.js'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { EndgameItem, Goal, PlayResult } from '../api'
import { engine, flip, type Score } from '../engine'
import { goalOf, PLAY_MOVES, playOutResult, type PlayEnd } from '../trainer'
import { Board } from './Board'
import { BoardFrame } from './BoardFrame'

const GOAL_MS = 2000
const REPLY_MS = 800

interface Props {
  item: EndgameItem
  onDone: (result: { result: PlayResult; goal: Goal; ms: number }) => void
}

/**
 * An endgame played out against the engine. The engine sets the goal from the start (win, or hold
 * the draw) and then defends (or attacks) at full strength; there are no hints.
 */
export function PlayOut({ item, onDone }: Props) {
  const { t } = useTranslation()
  const game = useRef(new Chess(item.fen))
  const [fen, setFen] = useState(item.fen)
  const [goal, setGoal] = useState<Goal | null>(null)
  const [thinking, setThinking] = useState(false)
  const [end, setEnd] = useState<{ result: PlayResult; why: string } | null>(null)
  const [started] = useState(() => Date.now())
  const [moves, setMoves] = useState(0)
  const reader = item.fen.split(' ')[1] as 'w' | 'b'

  useEffect(() => {
    let live = true
    engine
      .analyse(item.fen, { movetime: GOAL_MS })
      .then((lines) => live && setGoal(lines[0] ? goalOf(lines[0].score) : 'draw'))
      .catch(() => live && setGoal('draw'))
    return () => {
      live = false
      engine.stop()
    }
  }, [item.fen])

  const finish = (g: Goal, e: PlayEnd, why: string) => setEnd({ result: playOutResult(g, e), why })

  /** If the game is over (by the rules), how; null if it goes on. */
  const over = (): PlayEnd | null => {
    const c = game.current
    if (c.isCheckmate()) return { kind: 'mate', readerWon: c.turn() !== reader }
    if (c.isDraw() || c.isStalemate() || c.isThreefoldRepetition() || c.isInsufficientMaterial()) return { kind: 'draw' }
    return null
  }

  const onMove = (from: string, to: string | null) => {
    if (!to || !goal || end || thinking || game.current.turn() !== reader) return false
    try {
      game.current.move({ from, to, promotion: 'q' })
    } catch {
      return false
    }
    setFen(game.current.fen())
    const done = moves + 1
    setMoves(done)
    const e = over()
    if (e) {
      finish(goal, e, e.kind === 'mate' ? t('train.mate') : t('train.drawn'))
      return true
    }
    setThinking(true)
    void engine.analyse(game.current.fen(), { movetime: REPLY_MS }).then(async (lines) => {
      const uci = lines[0]?.pv[0]
      if (uci) game.current.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] ?? 'q' })
      setFen(game.current.fen())
      setThinking(false)
      const after = over()
      if (after) finish(goal, after, after.kind === 'mate' ? t('train.mated') : t('train.drawn'))
      else if (done >= PLAY_MOVES) {
        const score: Score = lines[0] ? flip(lines[0].score) : { cp: 0 }
        const final = (await engine.analyse(game.current.fen(), { movetime: GOAL_MS }))[0]
        finish(goal, { kind: 'limit', score: final ? final.score : score }, t('train.outOfMoves'))
      }
    }).catch(() => setThinking(false))
    return true
  }

  return (
    <div className="play-out">
      <div className="calc-head">
        <strong>{t(reader === 'w' ? 'train.youWhite' : 'train.youBlack')}</strong>
        <span>{goal ? t(`train.goal.${goal}`) : t('train.findingGoal')}</span>
        <span className="hint">{t('train.movesLeft', { count: Math.max(0, PLAY_MOVES - moves) })}</span>
      </div>
      <BoardFrame sizeKey="solveBoardSize">
        <Board id="play-board" fen={fen} orientation={reader === 'w' ? 'white' : 'black'} animate mover={reader} onMove={goal && !end ? onMove : undefined} />
      </BoardFrame>
      {thinking && <p className="hint">{t('train.engineThinking')}</p>}
      {!end && goal && (
        <div className="nav">
          <button type="button" onClick={() => finish(goal, { kind: 'resigned' }, t('train.resigned'))}>{t('train.resign')}</button>
        </div>
      )}
      {end && goal && (
        <div className={`calc-grade ${end.result === 'met' ? 'full' : end.result === 'partial' ? 'first' : 'wrong'}`}>
          <p><strong>{t(`train.play.${end.result}`)}</strong> — {end.why}</p>
          <p className="hint">{t('train.sourceBook', { book: item.bookTitle })}</p>
          <button type="button" className="primary" onClick={() => onDone({ result: end.result, goal, ms: Date.now() - started })}>{t('train.next')}</button>
        </div>
      )}
    </div>
  )
}
