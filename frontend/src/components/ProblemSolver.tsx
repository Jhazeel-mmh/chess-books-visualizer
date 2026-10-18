import { Fragment, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Chess } from 'chess.js'
import type { Diagram } from '../api'
import { engine, flip, formatScore } from '../engine'
import { sanLine, type ExploreMove } from '../explore'
import { displaySan, lineNumbers } from '../notation'
import { formatTime, isoNow, type ProblemRecord } from '../progress'
import { load } from '../storage'
import { endsInMate, judge, mainLine, nextMove, play, solverMoves, type BookTree, type EngineLike, type Move, type Verdict } from '../solve'
import { Board, type BoardArrow } from './Board'
import { BoardFrame } from './BoardFrame'
import { EngineLine } from './EngineLine'
import { useEngineSwitch } from '../useEngineSwitch'

interface Props {
  problem: Diagram
  /** All the book's moves by id (the problem's solution is among them, if the book has one). */
  tree: BookTree
  number: string
  previous?: ProblemRecord
  onDone: (record: ProblemRecord) => void
  onNext: () => void
  onRetry: () => void
  onOpenInBook: () => void
}

type Phase = 'playing' | 'checking' | 'solved' | 'failed'

interface State {
  fen: string
  /** Where the book's solution stands; undefined once the reader left it (the engine judges from there). */
  node?: string
  /** Moves the reader has got right. */
  plies: number
  phase: Phase
  tries: number
  hints: number
  hintLevel: number
  hintMove: Move | null
  message: { kind: 'good' | 'bad' | 'info'; text: string } | null
  /** The engine's better move after a wrong one, shown on request. */
  better?: string
  last: Move | null
  /** The solution, stepped through after it is shown or found. */
  review: { start: string; moves: { fen: string; uci: string; san: string }[]; at: number } | null
}

const REPLY_MS = 450
const TAKE_BACK_MS = 900

/** Engine calls that fail (no WASM support, say) just leave the judging to the book. */
const safeEngine: EngineLike = {
  analyse: (fen, options) => engine.analyse(fen, options).catch(() => []),
}

/** One problem: the board to play on, the task, and help when needed. */
export function ProblemSolver({ problem, tree, number, previous, onDone, onNext, onRetry, onOpenInBook }: Props) {
  const { t, i18n } = useTranslation()
  const solution = problem.solution ?? undefined
  const start = (solution && tree.get(solution)?.fen) || `${problem.placement} ${problem.turn ?? 'w'} - - 0 1`
  const side = start.split(' ')[1] as 'w' | 'b'
  const expected = solution ? Math.max(1, solverMoves(tree, solution)) : 1
  const mateLine = solution ? endsInMate(tree, solution) : false

  const lang = i18n.resolvedLanguage ?? 'en'
  const [figurines] = useState(() => load('figurines', false))
  const [preview, setPreview] = useState<{ from: string; moves: ExploreMove[]; at: number } | null>(null)
  const previewNumbers = preview ? lineNumbers(preview.from, preview.moves.length) : []
  const [s, setS] = useState<State>({
    fen: start, node: solution, plies: 0, phase: 'playing', tries: 0, hints: 0, hintLevel: 0, hintMove: null,
    message: null, last: null, review: null,
  })
  const [started] = useState(() => Date.now())
  const [now, setNow] = useState(started)
  useEffect(() => {
    if (s.phase === 'solved' || s.phase === 'failed') return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [s.phase])

  const finish = (state: State, result: 'won' | 'shown'): State => {
    const record: ProblemRecord = {
      result: result === 'shown' ? 'failed' : state.tries || state.hints ? 'helped' : 'solved',
      tries: state.tries,
      hints: state.hints,
      ms: Date.now() - started,
      at: isoNow(),
    }
    onDone(record)
    return { ...state, phase: result === 'shown' ? 'failed' : 'solved' }
  }

  const onMove = (from: string, to: string | null) => {
    if (s.phase !== 'playing' || !to) return false
    const move = { from, to }
    const after = play(s.fen, move)
    if (!after) return false
    const before = s
    setS({ ...before, fen: after.fen, phase: 'checking', last: move, message: { kind: 'info', text: t('solve.checking') }, hintLevel: 0, hintMove: null })
    void judge(before.fen, move, tree, before.node, mateLine, safeEngine).then((v) => respond(before, after.fen, move, v))
    return true
  }

  /** What happens after the judge's verdict on ``move``, played from ``before`` to ``fen``. */
  const respond = (before: State, fen: string, move: Move, v: Verdict) => {
    const right = (text: string, node: string | undefined, reply?: { fen: string; last: Move }) => {
      const state: State = { ...before, fen, node, plies: before.plies + 1, phase: 'playing', message: { kind: 'good', text }, last: move }
      const lineEnds = node ? !tree.get(node)?.children.length : state.plies >= expected
      if (lineEnds || !reply) {
        setS(finish({ ...state, review: solvedReview() }, 'won'))
        return
      }
      setS({ ...state, phase: 'checking' })
      setTimeout(() => {
        const replyNode = node ? tree.get(tree.get(node)!.children[0]) : undefined
        const next: State = { ...state, fen: reply.fen, node: replyNode?.id, last: reply.last, phase: 'playing' }
        const done = replyNode ? !replyNode.children.length : false
        setS(done ? finish({ ...next, review: solvedReview() }, 'won') : next)
      }, REPLY_MS)
    }
    const bookReply = (node: string) => {
      const reply = tree.get(tree.get(node)?.children[0] ?? '')
      return reply?.uci ? { fen: reply.fen, last: { from: reply.uci.slice(0, 2), to: reply.uci.slice(2, 4) } } : undefined
    }
    switch (v.kind) {
      case 'book':
        return right(t('solve.right'), v.node, bookReply(v.node))
      case 'alternative':
        return right(t('solve.alternative'), v.node, bookReply(v.node))
      case 'mate':
        return setS(finish({ ...before, fen, last: move, plies: before.plies + 1, message: { kind: 'good', text: t('solve.mate') } }, 'won'))
      case 'engine': {
        const reply = v.reply ? play(fen, { from: v.reply.slice(0, 2), to: v.reply.slice(2, 4), promotion: v.reply[4] }) : null
        return right(
          t('solve.engineGood', { score: formatScore(side === 'w' ? v.score : flip(v.score)) }),
          undefined,
          reply ? { fen: reply.fen, last: { from: v.reply!.slice(0, 2), to: v.reply!.slice(2, 4) } } : undefined,
        )
      }
      case 'refuted':
        return takeBack(before, fen, t('solve.refuted', { line: v.line.slice(0, 6).join(' ') }))
      case 'wrong':
        return takeBack(before, fen, t('solve.wrong'), v.best)
    }
  }

  const takeBack = (before: State, fen: string, text: string, better?: string) => {
    setS({ ...before, fen, phase: 'checking', tries: before.tries + 1, message: { kind: 'bad', text }, better })
    setTimeout(() => setS((cur) => ({ ...cur, fen: before.fen, phase: 'playing', last: before.last })), TAKE_BACK_MS)
  }

  /** Once solved, the book's whole line can be stepped through. */
  const solvedReview = (): State['review'] => (solution ? { start, moves: mainLine(tree, solution).map(toStep), at: 0 } : null)

  const hint = async () => {
    if (s.phase !== 'playing') return
    const move = s.hintMove ?? (await nextMove(s.fen, tree, s.node, safeEngine))
    if (!move) return
    setS((cur) => ({ ...cur, hintMove: move, hintLevel: Math.min(3, cur.hintLevel + 1), hints: cur.hints + 1 }))
  }

  const showSolution = async () => {
    if (s.phase !== 'playing') return
    const here = s
    let moves: { fen: string; uci: string; san: string }[]
    if (here.node && tree.get(here.node)?.children.length) {
      moves = mainLine(tree, here.node).map(toStep)
    } else {
      setS({ ...here, phase: 'checking', message: { kind: 'info', text: t('solve.thinking') } })
      const line = (await safeEngine.analyse(here.fen, { movetime: 2500 }))[0]
      moves = line ? uciSteps(here.fen, line.pv.slice(0, 8)) : []
    }
    setS(finish({ ...here, message: null, review: { start: here.fen, moves, at: 0 } }, 'shown'))
  }

  // Keys: H hint, S solution, N next, R retry.
  const keys = useRef({ hint, showSolution, onNext, onRetry })
  useEffect(() => {
    keys.current = { hint, showSolution, onNext, onRetry }
  })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return
      const action = { h: keys.current.hint, s: keys.current.showSolution, n: keys.current.onNext, r: keys.current.onRetry }[e.key.toLowerCase()]
      if (action) {
        e.preventDefault()
        void action()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const review = s.review
  const reviewFen = review ? (review.at ? review.moves[review.at - 1].fen : review.start) : s.fen
  // After the problem: the engine's line, clicked, is shown on the board until "back to the solution".
  const previewFen = preview ? (preview.at ? preview.moves[preview.at - 1].fen : preview.from) : null
  const shownFen = previewFen ?? reviewFen
  // The engine's line, clicked: played on the board after what is shown (the moves after it are dropped).
  const playLine = (moves: ExploreMove[]) => {
    if (!preview) return setPreview({ from: shownFen, moves, at: moves.length })
    const all = [...preview.moves.slice(0, preview.at), ...moves]
    setPreview({ ...preview, moves: all, at: all.length })
  }
  const arrows: BoardArrow[] = []
  const highlights: Record<string, CSSProperties> = {}
  if (s.last && !review) {
    highlights[s.last.from] = LAST
    highlights[s.last.to] = LAST
  }
  if (s.hintMove && s.hintLevel >= 1) highlights[s.hintMove.from] = HINT
  if (s.hintMove && s.hintLevel >= 2) highlights[s.hintMove.to] = HINT
  if (s.hintMove && s.hintLevel >= 3) arrows.push({ from: s.hintMove.from, to: s.hintMove.to })
  if (preview?.at) {
    const last = preview.moves[preview.at - 1]
    highlights[last.from] = LAST
    if (last.to) highlights[last.to] = LAST
  } else if (review && review.at < review.moves.length) {
    const next = review.moves[review.at].uci
    arrows.push({ from: next.slice(0, 2), to: next.slice(2, 4), color: 'rgba(30, 90, 200, 0.85)' })
  }
  const done = s.phase === 'solved' || s.phase === 'failed'
  // The engine only once the problem is over: while solving it would be a hint.
  const [engineOn, toggleEngine] = useEngineSwitch(done)
  const elapsed = done ? 0 : now - started

  return (
    <div className="solver-main">
      <div className="problem-card">
        <strong>{t('solve.problem', { number })}</strong>
        <span className={`side side-${side}`}>{side === 'w' ? t('solve.whiteToPlay') : t('solve.blackToPlay')}</span>
        {problem.points ? <span className="hint">{t('solve.points', { count: problem.points })}</span> : null}
        {!solution && <span className="hint">{t('solve.engineOnly')}</span>}
        {!done && <span className="timer">{formatTime(elapsed)}</span>}
        {previous && <span className={`hint result-${previous.result}`}>{t(`solve.previous.${previous.result}`)}</span>}
      </div>
      <BoardFrame sizeKey="solveBoardSize">
        <Board
          id="solver-board"
          fen={shownFen}
          orientation={side === 'w' ? 'white' : 'black'}
          animate
          onMove={s.phase === 'playing' ? onMove : undefined}
          mover={side}
          arrows={arrows}
          highlights={highlights}
        />
      </BoardFrame>
      {s.message && <p className={`solve-message ${s.message.kind}`}>{s.message.text}</p>}
      {s.better && s.phase === 'playing' && (
        <button type="button" className="link" onClick={() => setS((cur) => ({ ...cur, message: { kind: 'info', text: t('solve.enginePrefers', { move: sanLine(cur.fen, [cur.better!], 1)[0] ?? cur.better }) }, better: undefined }))}>
          {t('solve.whatIsBetter')}
        </button>
      )}
      {done && engineOn && <EngineLine fen={shownFen} lang={lang} figurines={figurines} onPlay={playLine} />}
      {preview && (
        <div className="review">
          <span className="hint">{t('solve.engineLine')}</span>
          <span className="review-moves">
            {preview.moves.map((m, i) => (
              <Fragment key={i}>
                {previewNumbers[i] && <span className="move-number">{previewNumbers[i]}</span>}
                <button type="button" className={`move${i + 1 === preview.at ? ' selected' : ''}`} onClick={() => setPreview({ ...preview, at: i + 1 })}>
                  {displaySan(m.label, lang, figurines)}
                </button>
              </Fragment>
            ))}
          </span>
          <button type="button" onClick={() => setPreview(null)}>{t('solve.backToSolution')}</button>
        </div>
      )}
      {review && (
        <div className="review">
          <span className="hint">{s.phase === 'failed' ? t('solve.solutionShown') : t('solve.solved')}</span>
          <span className="review-moves">
            {review.moves.map((m, i) => (
              <button key={i} type="button" className={`move${i + 1 === review.at && !preview ? ' selected' : ''}`} onClick={() => { setPreview(null); setS((cur) => ({ ...cur, review: { ...review, at: i + 1 } })) }}>
                {m.san}
              </button>
            ))}
          </span>
        </div>
      )}
      <div className="nav">
        {!done ? (
          <>
            <button type="button" onClick={() => void hint()} disabled={s.phase !== 'playing'} title="H">{t('solve.hint')}</button>
            <button type="button" onClick={() => void showSolution()} disabled={s.phase === 'checking'} title="S">{t('solve.showSolution')}</button>
          </>
        ) : (
          <>
            {preview ? (
              <>
                <button type="button" onClick={() => setPreview({ ...preview, at: Math.max(0, preview.at - 1) })} aria-label={t('reader.prev')}>◀</button>
                <button type="button" onClick={() => setPreview({ ...preview, at: Math.min(preview.moves.length, preview.at + 1) })} aria-label={t('reader.next')}>▶</button>
              </>
            ) : review && (
              <>
                <button type="button" onClick={() => setS((cur) => ({ ...cur, review: { ...review, at: Math.max(0, review.at - 1) } }))} aria-label={t('reader.prev')}>◀</button>
                <button type="button" onClick={() => setS((cur) => ({ ...cur, review: { ...review, at: Math.min(review.moves.length, review.at + 1) } }))} aria-label={t('reader.next')}>▶</button>
              </>
            )}
            <button type="button" className={engineOn ? 'active' : ''} onClick={toggleEngine} aria-pressed={engineOn} title={t('engine.keyHint')}>
              {t('engine.toggle')}
            </button>
            <button type="button" onClick={onRetry} title="R">{t('solve.retry')}</button>
            <button type="button" onClick={onOpenInBook}>{t('solve.openInBook')}</button>
          </>
        )}
        <button type="button" className="primary" onClick={onNext} title="N">{t('solve.next')}</button>
      </div>
      <p className="hint">{t('solve.keys')}</p>
    </div>
  )
}

const LAST: CSSProperties = { background: 'rgba(242, 201, 76, 0.35)' }
const HINT: CSSProperties = { background: 'rgba(30, 140, 220, 0.4)' }

function toStep(n: { fen: string; uci: string | null; san: string | null }) {
  return { fen: n.fen, uci: n.uci ?? '', san: n.san ?? '' }
}

/** Engine moves (UCI) as steps with positions and SAN. */
function uciSteps(fen: string, uci: string[]) {
  const game = new Chess(fen)
  const out: { fen: string; uci: string; san: string }[] = []
  for (const m of uci) {
    try {
      const move = game.move({ from: m.slice(0, 2), to: m.slice(2, 4), promotion: m[4] })
      out.push({ fen: game.fen(), uci: move.lan, san: move.san })
    } catch {
      break
    }
  }
  return out
}
