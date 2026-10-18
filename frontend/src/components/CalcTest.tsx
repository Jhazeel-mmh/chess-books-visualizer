import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CalcItem, CalcResult } from '../api'
import { engine } from '../engine'
import { formatTime } from '../progress'
import { mainLine, play } from '../solve'
import { gradeLine, treeOf, type LineGrade } from '../trainer'
import { Board } from './Board'
import { BoardFrame } from './BoardFrame'

interface Played {
  uci: string
  san: string
  fen: string
}

interface Props {
  item: CalcItem
  /** Time for this position (ms); in a test the clock is shared, so it is the time left for all. */
  timeMs: number
  /** Show the grade and the book's solution at once (a session); a test shows them all at the end. */
  feedback: boolean
  onDone: (result: { result: CalcResult; ms: number; line: string[] }) => void
}

/**
 * A calculation test: an unseen position, no hints, a clock. The reader works out the line to the
 * end and then enters it whole (both sides' moves) before handing it in.
 */
export function CalcTest({ item, timeMs, feedback, onDone }: Props) {
  const { t } = useTranslation()
  const tree = useMemo(() => treeOf(item.tree), [item])
  const [line, setLine] = useState<Played[]>([])
  const [grade, setGrade] = useState<LineGrade | null>(null)
  const [grading, setGrading] = useState(false)
  const [started] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  const [spent, setSpent] = useState(0)
  const fen = line.length ? line[line.length - 1].fen : item.fen
  const side = item.fen.split(' ')[1] === 'b' ? 'black' : 'white'
  const left = Math.max(0, timeMs - (now - started))

  const submit = async () => {
    if (grading || grade) return
    setGrading(true)
    const ms = Date.now() - started
    setSpent(ms)
    const g = await gradeLine(item.fen, line.map((m) => m.uci), tree, item.root, engine).catch(() => null)
    const result: LineGrade = g ?? { result: 'wrong', first: { kind: 'wrong' }, byEngine: 0 }
    setGrading(false)
    if (feedback) setGrade(result)
    else onDone({ result: result.result, ms, line: line.map((m) => m.san) })
  }

  // The clock: when it runs out, the line so far is handed in.
  const submitRef = useRef(submit)
  useEffect(() => {
    submitRef.current = submit
  })
  useEffect(() => {
    if (grade || grading) return
    const timer = setInterval(() => {
      setNow(Date.now())
      if (Date.now() - started >= timeMs) void submitRef.current()
    }, 500)
    return () => clearInterval(timer)
  }, [grade, grading, started, timeMs])

  const onMove = (from: string, to: string | null) => {
    if (!to || grade || grading) return false
    const m = play(fen, { from, to })
    if (!m) return false
    setLine([...line, { uci: m.uci, san: m.san, fen: m.fen }])
    return true
  }

  const firstNumber = Number(item.fen.split(' ')[5] ?? 1)
  const blackFirst = item.fen.split(' ')[1] === 'b'
  const numbered = (sans: string[]) =>
    sans
      .map((san, i) => {
        const ply = i + (blackFirst ? 1 : 0)
        const n = firstNumber + Math.floor(ply / 2)
        if (ply % 2 === 0) return `${n}.${san}`
        return i === 0 ? `${n}...${san}` : san
      })
      .join(' ')
  const book = mainLine(tree, item.root).map((n) => n.san ?? '')

  return (
    <div className="calc-test">
      <div className="calc-head">
        <strong>{t(side === 'white' ? 'train.whiteToPlay' : 'train.blackToPlay')}</strong>
        {!grade && <span className={`clock${left < 60000 ? ' low' : ''}`}>{formatTime(left)}</span>}
      </div>
      <BoardFrame sizeKey="solveBoardSize">
        <Board id="calc-board" fen={fen} orientation={side} animate onMove={grade ? undefined : onMove} />
      </BoardFrame>
      <p className="calc-line">
        {line.length ? numbered(line.map((m) => m.san)) : <span className="hint">{t('train.enterLine')}</span>}
      </p>
      {!grade && (
        <div className="nav">
          <button type="button" onClick={() => setLine(line.slice(0, -1))} disabled={!line.length || grading}>{t('fix.undo')}</button>
          <button type="button" onClick={() => setLine([])} disabled={!line.length || grading}>{t('train.clear')}</button>
          <button type="button" className="primary" onClick={() => void submit()} disabled={grading}>
            {grading ? t('solve.checking') : t('train.submit')}
          </button>
        </div>
      )}
      {grade && (
        <div className={`calc-grade ${grade.result}`}>
          <p><strong>{t(`train.grade.${grade.result}`)}</strong></p>
          {grade.missedDefence && <p>{t('train.missedDefence', { move: grade.missedDefence })}</p>}
          {grade.bookMove && <p>{t('train.bookMove', { move: grade.bookMove })}</p>}
          {grade.goesOn && <p>{t('train.goesOn', { moves: grade.goesOn.join(' ') })}</p>}
          {grade.short && <p>{t('train.short')}</p>}
          {grade.byEngine > 0 && <p className="hint">{t('train.byEngine', { count: grade.byEngine })}</p>}
          <p>{t('train.bookLine')}: <strong>{numbered(book)}</strong></p>
          <p className="hint">{t('train.source', { book: item.bookTitle, label: item.label ?? '—' })} · {formatTime(spent)}</p>
          <button type="button" className="primary" onClick={() => onDone({ result: grade.result, ms: spent, line: line.map((m) => m.san) })}>
            {t('train.next')}
          </button>
        </div>
      )}
    </div>
  )
}
