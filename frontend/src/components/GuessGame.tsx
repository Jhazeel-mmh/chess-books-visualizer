import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Game, MoveNode } from '../api'
import { isoNow } from '../progress'
import { engine, flip, scoreValue } from '../engine'
import { complete, EMPTY_PROGRESS, type Progress } from '../progress'
import { play, type BookTree, type Move } from '../solve'
import { useUserData } from '../userData'
import { Board, type BoardArrow } from './Board'
import { BoardFrame } from './BoardFrame'

const AUTO_MS = 600
const ENGINE_MS = 1000

interface Props {
  bookId: string
  games: Game[]
  tree: BookTree
  onRead?: (nodeId: string) => void
  /** In the trainer: one game, from a move, for a number of guesses, then ``onDone``. */
  run?: { from: number; moves: number; onDone: (score: { same: number; good: number; total: number; at: number }) => void }
}

interface Session {
  /** Index into the game's main line of the position on the board. */
  at: number
  same: number
  good: number
  total: number
  message: { kind: 'good' | 'bad' | 'info'; text: string } | null
  /** The reader's guess, shown next to the game's move. */
  guess: Move | null
  busy: boolean
}

const NEW: Session = { at: 0, same: 0, good: 0, total: 0, message: null, guess: null, busy: false }

/** Guess the move: play one side of a game from the book, and see how your moves compare. */
export function GuessGame({ bookId, games, tree, onRead, run }: Props) {
  const { t } = useTranslation()
  const [gameId, setGameId] = useState(games[0]?.id ?? '')
  const [side, setSide] = useState<'w' | 'b'>('w')
  const [s, setS] = useState<Session>(() => ({ ...NEW, at: run?.from ?? 0 }))
  const saved = useUserData<Progress>(bookId, 'progress', EMPTY_PROGRESS)
  const game = games.find((g) => g.id === gameId)
  const title = game?.title ?? t('reader.untitled', { n: games.indexOf(game!) + 1 })

  const line: MoveNode[] = useMemo(() => {
    const out: MoveNode[] = []
    let n = game ? tree.get(game.root) : undefined
    while (n) {
      out.push(n)
      n = n.children.length ? tree.get(n.children[0]) : undefined
    }
    return out
  }, [game, tree])

  const here = line[s.at]
  const toMove = here?.fen.split(' ')[1] as 'w' | 'b' | undefined
  const finished = s.at >= line.length - 1 || (!!run && s.total >= run.moves)

  // The other side's moves are played for the reader.
  const savedRef = useRef(saved)
  useEffect(() => {
    savedRef.current = saved
  })
  useEffect(() => {
    if (!here || finished || s.busy || toMove === side) return
    const timer = setTimeout(() => setS((cur) => ({ ...cur, at: cur.at + 1, guess: null })), AUTO_MS)
    return () => clearTimeout(timer)
  }, [here, finished, s.busy, toMove, side])
  useEffect(() => {
    if (!finished || !s.total || !game || run) return
    savedRef.current.update((old) => {
      const p = complete(old)
      return { ...p, guesses: { ...p.guesses, [title]: { same: s.same, good: s.good, total: s.total, at: isoNow() } } }
    })
  }, [finished, s.same, s.good, s.total, game, title, run])

  const onMove = (from: string, to: string | null) => {
    if (!here || !to || finished || s.busy || toMove !== side) return false
    const move = { from, to }
    const mine = play(here.fen, move)
    const theirs = line[s.at + 1]
    if (!mine || !theirs) return false
    setS((cur) => ({ ...cur, busy: true, guess: move, message: { kind: 'info', text: t('solve.checking') } }))
    void compare(mine.fen, theirs, mine.uci).then((verdict) =>
      setS((cur) => ({
        ...cur,
        busy: false,
        at: cur.at + 1,
        total: cur.total + 1,
        same: cur.same + Number(verdict.kind === 'same'),
        good: cur.good + Number(verdict.kind === 'good'),
        message: verdict.kind === 'same'
          ? { kind: 'good', text: t('guess.same') }
          : verdict.kind === 'good'
            ? { kind: 'good', text: t('guess.good', { move: theirs.san }) }
            : { kind: 'bad', text: verdict.loss !== undefined ? t('guess.worse', { move: theirs.san, pawns: (verdict.loss / 100).toFixed(1) }) : t('guess.different', { move: theirs.san }) },
      })),
    )
    return true
  }

  const arrows: BoardArrow[] = []
  if (s.guess && s.message && s.message.kind !== 'info') arrows.push({ from: s.guess.from, to: s.guess.to, color: s.message.kind === 'good' ? 'rgba(21, 120, 27, 0.8)' : 'rgba(200, 50, 50, 0.8)' })
  const lastMove = here?.uci
  const highlights = lastMove && s.at > 0 ? { [lastMove.slice(0, 2)]: LAST, [lastMove.slice(2, 4)]: LAST } : undefined

  return (
    <div className="solver-main">
      <div className="problem-card">
        {run ? (
          <strong>{title}</strong>
        ) : (
          <select value={gameId} onChange={(e) => { setGameId(e.target.value); setS(NEW) }} aria-label={t('reader.game')}>
            {games.map((g, i) => (
              <option key={g.id} value={g.id}>{g.title ?? t('reader.untitled', { n: i + 1 })}</option>
            ))}
          </select>
        )}
        <label className="check">
          <input type="radio" name="side" checked={side === 'w'} disabled={!!run && s.total > 0} onChange={() => { setSide('w'); setS({ ...NEW, at: run?.from ?? 0 }) }} />
          {t('guess.playWhite')}
        </label>
        <label className="check">
          <input type="radio" name="side" checked={side === 'b'} disabled={!!run && s.total > 0} onChange={() => { setSide('b'); setS({ ...NEW, at: run?.from ?? 0 }) }} />
          {t('guess.playBlack')}
        </label>
      </div>
      <BoardFrame sizeKey="solveBoardSize">
        {here && (
          <Board
            id="guess-board"
            fen={here.fen}
            orientation={side === 'w' ? 'white' : 'black'}
            animate
            onMove={!finished && toMove === side && !s.busy ? onMove : undefined}
            mover={side}
            arrows={arrows}
            highlights={highlights}
          />
        )}
      </BoardFrame>
      {s.message && <p className={`solve-message ${s.message.kind}`}>{s.message.text}</p>}
      <p className="score">{t('guess.score', { same: s.same, good: s.good, total: s.total })}</p>
      {!run && (
        <div className="nav">
          <button type="button" onClick={() => setS(NEW)}>{t('guess.restart')}</button>
          {here && onRead && <button type="button" onClick={() => onRead(here.id)}>{t('guess.read')}</button>}
        </div>
      )}
      {finished && <p className="hint">{t('guess.finished', { same: s.same, good: s.good, total: s.total })}</p>}
      {finished && run && !s.busy && (
        <button type="button" className="primary" onClick={() => run.onDone({ same: s.same, good: s.good, total: s.total, at: s.at })}>{t('train.next')}</button>
      )}
    </div>
  )
}

const LAST = { background: 'rgba(242, 201, 76, 0.35)' }

/** The reader's move against the game's: the same, as good by the engine, or worse by how much. */
async function compare(afterMine: string, theirs: MoveNode, mine: string): Promise<{ kind: 'same' | 'good' | 'worse'; loss?: number }> {
  if (theirs.uci === mine) return { kind: 'same' }
  try {
    const a = (await engine.analyse(afterMine, { movetime: ENGINE_MS }))[0]
    const b = (await engine.analyse(theirs.fen, { movetime: ENGINE_MS }))[0]
    if (!a || !b) return { kind: 'worse' }
    // Both scores are for the side to move after the move: the opponent. Flip to the mover's view.
    const loss = scoreValue(flip(b.score)) - scoreValue(flip(a.score))
    return loss <= 30 ? { kind: 'good' } : { kind: 'worse', loss: Math.min(loss, 999) }
  } catch {
    return { kind: 'worse' }
  }
}
