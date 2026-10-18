import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Analysis, Diagram } from '../api'
import { GuessGame } from '../components/GuessGame'
import { longGames } from '../games'
import { ProblemSolver } from '../components/ProblemSolver'
import { complete, cycleTime, EMPTY_PROGRESS, formatTime, isoNow, openCycle, type Cycle, type ProblemRecord, type Progress } from '../progress'
import type { BookTree } from '../solve'
import { useUserData } from '../userData'

/** Where "open in the book" takes the reader. */
export type BookTarget = { kind: 'node' | 'diagram'; id: string }

interface Props {
  bookId: string
  analysis: Analysis
  onOpenInBook: (target: BookTarget) => void
}

type Filter = 'all' | 'unsolved' | 'failed'
/** In a cycle, how long the result of a problem stays on screen before the next one opens. */
const CYCLE_PAUSE_MS = 1500
const ALL = '\u0000all'

/** Solving mode: the book's problems (and its games, to guess their moves), with the book hidden. */
export default function Solver({ bookId, analysis, onOpenInBook }: Props) {
  const { t } = useTranslation()
  const problems = useMemo(() => analysis.diagrams.filter((d) => d.problem && d.key), [analysis])
  const games = useMemo(() => longGames(analysis.games), [analysis])
  const tree: BookTree = useMemo(() => new Map(analysis.games.flatMap((g) => g.nodes.map((n) => [n.id, n]))), [analysis])
  const [tab, setTab] = useState<'problems' | 'games'>(problems.length ? 'problems' : 'games')

  const saved = useUserData<Progress>(bookId, 'progress', EMPTY_PROGRESS)
  const progress = complete(saved.data)
  const results = progress.problems

  const sections = useMemo(() => [...new Set(problems.map((p) => p.section ?? ''))], [problems])
  const [set, setSet] = useState(ALL)
  const [filter, setFilter] = useState<Filter>('all')
  const inSet = problems.filter((p) => set === ALL || (p.section ?? '') === set)
  const listed = inSet.filter((p) => {
    const r = results[p.key!]?.result
    return filter === 'all' || (filter === 'unsolved' ? r !== 'solved' : r === 'failed')
  })

  const cycle = openCycle(progress)
  const [currentId, setCurrentId] = useState<string | null>(() => problems.find((p) => !results[p.key!])?.id ?? problems[0]?.id ?? null)
  const [attempt, setAttempt] = useState(0)
  const current = problems.find((p) => p.id === currentId)

  const number = (p: Diagram) => p.label ?? String(problems.indexOf(p) + 1)

  const open = (p: Diagram | undefined) => {
    if (!p) return
    setCurrentId(p.id)
    setAttempt((a) => a + 1)
  }
  /** The next problem: in the cycle, the next not yet done; otherwise the next listed one not solved. */
  const next = () => {
    if (cycle) {
      const key = cycle.problems.find((k) => !cycle.results[k] && k !== current?.key)
      return open(problems.find((p) => p.key === key))
    }
    const from = listed.findIndex((p) => p.id === currentId)
    open(listed.slice(from + 1).find((p) => results[p.key!]?.result !== 'solved') ?? listed[from + 1])
  }
  // In a cycle the clock runs across the whole set: the next problem opens by itself.
  const nextRef = useRef(next)
  useEffect(() => {
    nextRef.current = next
  })

  const done = (record: ProblemRecord) => {
    const key = current!.key!
    if (cycle?.problems.includes(key)) setTimeout(() => nextRef.current(), CYCLE_PAUSE_MS)
    saved.update((old) => {
      const p = complete(old)
      const cycles = p.cycles.map((c) =>
        c === openCycle(p) && c.problems.includes(key) && !c.results[key]
          ? finishIfComplete({ ...c, results: { ...c.results, [key]: { result: record.result, ms: record.ms } } })
          : c,
      )
      return { ...p, problems: { ...p.problems, [key]: record }, cycles }
    })
  }

  const startCycle = () => {
    const keys = inSet.map((p) => p.key!)
    const name = set === ALL ? '' : set
    const n = progress.cycles.filter((c) => c.set === name).length + 1
    const c: Cycle = { n, set: name, started: isoNow(), problems: keys, results: {} }
    saved.update((old) => ({ ...complete(old), cycles: [...complete(old).cycles, c] }))
    open(inSet[0])
  }
  const stopCycle = () =>
    saved.update((old) => {
      const p = complete(old)
      return { ...p, cycles: p.cycles.map((c) => (c === openCycle(p) ? { ...c, finished: isoNow() } : c)) }
    })

  const counts = (list: Diagram[]) => {
    const solved = list.filter((p) => results[p.key!]?.result === 'solved' || results[p.key!]?.result === 'helped').length
    return { solved, total: list.length }
  }

  return (
    <div className="solver">
      <aside className="solver-side">
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'problems'} className={tab === 'problems' ? 'active' : ''} onClick={() => setTab('problems')} disabled={!problems.length}>
            {t('solve.problems', { count: problems.length })}
          </button>
          <button type="button" role="tab" aria-selected={tab === 'games'} className={tab === 'games' ? 'active' : ''} onClick={() => setTab('games')} disabled={!games.length}>
            {t('guess.tab', { count: games.length })}
          </button>
        </div>

        {tab === 'problems' && (
          <>
            {sections.length > 1 && (
              <select value={set} onChange={(e) => setSet(e.target.value)} aria-label={t('solve.set')}>
                <option value={ALL}>{t('solve.allProblems')}</option>
                {sections.map((sec) => (
                  <option key={sec} value={sec}>{sec || t('solve.noSection')}</option>
                ))}
              </select>
            )}
            <div className="filters">
              {(['all', 'unsolved', 'failed'] as Filter[]).map((f) => (
                <label key={f} className="check">
                  <input type="radio" name="filter" checked={filter === f} onChange={() => setFilter(f)} />
                  {t(`solve.filter.${f}`)}
                </label>
              ))}
            </div>
            <Score {...counts(inSet)} />
            <CyclePanel cycle={cycle} previous={lastFinished(progress, set === ALL ? '' : set)} onStart={startCycle} onStop={stopCycle} />
            <ol className="problem-list">
              {listed.map((p) => {
                const r = results[p.key!]
                return (
                  <li key={p.id}>
                    <button type="button" className={`link${p.id === currentId ? ' current' : ''}`} onClick={() => open(p)}>
                      <span className={`mark result-${r?.result ?? 'none'}`} aria-hidden="true">{RESULT_MARK[r?.result ?? 'none']}</span>
                      {number(p)}
                      {r && <span className="hint"> {formatTime(r.ms)}</span>}
                    </button>
                  </li>
                )
              })}
            </ol>
          </>
        )}
        {tab === 'games' && <p className="hint">{t('guess.intro')}</p>}
      </aside>

      {tab === 'problems' && current && (
        <ProblemSolver
          key={`${current.id}-${attempt}`}
          problem={current}
          tree={tree}
          number={number(current)}
          previous={results[current.key!]}
          onDone={done}
          onNext={next}
          onRetry={() => setAttempt((a) => a + 1)}
          onOpenInBook={() => onOpenInBook(current.solution ? { kind: 'node', id: current.solution } : { kind: 'diagram', id: current.id })}
        />
      )}
      {tab === 'problems' && !current && <p className="notice">{t('solve.none')}</p>}
      {tab === 'games' && <GuessGame bookId={bookId} games={games} tree={tree} onRead={(id) => onOpenInBook({ kind: 'node', id })} />}
    </div>
  )
}

const RESULT_MARK = { solved: '✓', helped: '◐', failed: '✗', none: '·' }

function finishIfComplete(c: Cycle): Cycle {
  return c.problems.every((k) => c.results[k]) ? { ...c, finished: isoNow() } : c
}

function lastFinished(p: Progress, set: string): Cycle | undefined {
  return [...p.cycles].reverse().find((c) => c.finished && c.set === set)
}

function Score({ solved, total }: { solved: number; total: number }) {
  const { t } = useTranslation()
  return (
    <div className="score">
      <span>{t('solve.score', { solved, total })}</span>
      <span className="progress-bar" aria-hidden="true">
        <span style={{ width: `${total ? (100 * solved) / total : 0}%` }} />
      </span>
    </div>
  )
}

/** The Woodpecker cycle: a timed run through the set, compared with the previous run. */
function CyclePanel({ cycle, previous, onStart, onStop }: { cycle?: Cycle; previous?: Cycle; onStart: () => void; onStop: () => void }) {
  const { t } = useTranslation()
  if (!cycle) {
    return (
      <div className="cycle">
        <button type="button" onClick={onStart} title={t('cycle.hint')}>{t('cycle.start')}</button>
        {previous && (
          <span className="hint">
            {t('cycle.last', { n: previous.n, time: formatTime(cycleTime(previous)), solved: solvedIn(previous), total: previous.problems.length })}
          </span>
        )}
      </div>
    )
  }
  const doneCount = Object.keys(cycle.results).length
  return (
    <div className="cycle running">
      <strong>{t('cycle.running', { n: cycle.n })}</strong>
      <span>{t('cycle.progress', { done: doneCount, total: cycle.problems.length, time: formatTime(cycleTime(cycle)) })}</span>
      {previous && <span className="hint">{t('cycle.previous', { time: formatTime(cycleTime(previous)) })}</span>}
      <button type="button" onClick={onStop}>{t('cycle.stop')}</button>
    </div>
  )
}

function solvedIn(c: Cycle): number {
  return Object.values(c.results).filter((r) => r.result !== 'failed').length
}
