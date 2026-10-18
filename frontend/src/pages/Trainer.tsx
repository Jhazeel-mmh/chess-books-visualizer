import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import {
  api, type BlockKind, type CalcItem, type Focus, type Game, type GuessItem, type ItemResult, type PlanBlock, type ReadingItem,
  type RunningSession, type TrainerBook, type TrainerRecord,
} from '../api'
import { CalcTest } from '../components/CalcTest'
import { GuessGame } from '../components/GuessGame'
import { PlayOut } from '../components/PlayOut'
import { formatTime, isoNow } from '../progress'
import { mainLine } from '../solve'
import { load, save } from '../storage'
import { advance, blockScore, cancelSession, finishSession, sessionDone, skipBlock, startSession, streak, treeOf, weekly } from '../trainer'
import { READING_KEY, useTrainer, type ReadingStart } from '../trainerStore'

const SUBJECTS: BlockKind[] = ['calculation', 'endgame', 'reading', 'guess']
const FOCUSES: (Focus | '')[] = ['', 'calculation', 'endgames', 'positional']
const MINUTES = [45, 50, 60]
const RATINGS = [1600, 1700, 1800, 1900, 2000]

export function Trainer() {
  const { t } = useTranslation()
  const { record, error, update } = useTrainer()
  if (error) return <main className="trainer"><p className="notice">{String(error)}</p></main>
  if (!record) return <main className="trainer"><p className="notice">{t('mode.loading')}</p></main>
  return (
    <main className="trainer">
      {record.current ? <Session record={record} current={record.current} update={update} /> : <Home record={record} update={update} />}
    </main>
  )
}

// --- Before a session ---------------------------------------------------------------------------

function Home({ record, update }: { record: TrainerRecord; update: (r: TrainerRecord) => void }) {
  const { t } = useTranslation()
  const books = useQuery({ queryKey: ['trainerBooks', record.roles, record.reading.book, record.sources], queryFn: api.trainerBooks })
  const start = useMutation({
    mutationFn: (test: boolean) => api.newSession(test),
    onSuccess: (plan) => update(startSession(record, plan, isoNow())),
  })
  const settings = record.settings
  const set = (changes: Partial<TrainerRecord['settings']>) => update({ ...record, settings: { ...settings, ...changes } })
  const [now] = useState(() => new Date())
  const weeks = weekly(record.sessions, now)
  const last = record.sessions[record.sessions.length - 1]
  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

  return (
    <>
      <section className="train-start">
        <h2>{t('train.title')}</h2>
        <p className="hint">{t('train.intro')}</p>
        <div className="train-buttons">
          <button type="button" className="primary big" disabled={start.isPending} onClick={() => start.mutate(false)}>
            {t('train.start', { minutes: settings.minutes })}
          </button>
          <button type="button" disabled={start.isPending} onClick={() => start.mutate(true)} title={t('train.testHint')}>
            {t('train.test')}
          </button>
        </div>
        {start.isPending && <p className="hint">{t('train.building')}</p>}
        {start.data && start.data.blocks.length === 0 && <p className="notice">{t('train.nothing')}</p>}
        {last?.note && <p className="train-note">{t('train.lastNote')} <em>{last.note}</em></p>}
      </section>

      <section className="train-settings">
        <label>
          {t('train.minutes')}
          <select value={settings.minutes} onChange={(e) => set({ minutes: Number(e.target.value) })}>
            {MINUTES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
        <label>
          {t('train.rating')}
          <select value={settings.rating} onChange={(e) => update({ ...record, level: null, settings: { ...settings, rating: Number(e.target.value) } })}>
            {RATINGS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <label>
          {t('train.focus')}
          <select value={settings.focus ?? ''} onChange={(e) => set({ focus: (e.target.value || null) as Focus | null })}>
            {FOCUSES.map((f) => <option key={f} value={f}>{t(`train.focusOf.${f || 'none'}`)}</option>)}
          </select>
        </label>
        {record.level !== null && <span className="hint">{t('train.level', { level: record.level.toFixed(2) })}</span>}
      </section>

      <SubjectBooks record={record} books={books.data ?? []} update={update} />

      <section className="train-stats">
        <h3>{t('train.progress')}</h3>
        <p>
          <strong>{t('train.streak', { count: streak(record.sessions, now) })}</strong> · {t('train.sessions', { count: record.sessions.length })}
        </p>
        <table>
          <thead>
            <tr>
              <th>{t('train.week')}</th><th>{t('train.sessionsShort')}</th><th>{t('train.minutesShort')}</th>
              <th>{t('train.block.calculation')}</th><th>{t('train.block.endgame')}</th><th>{t('train.block.guess')}</th><th>{t('train.pages')}</th>
            </tr>
          </thead>
          <tbody>
            {weeks.map((w) => (
              <tr key={w.week}>
                <td>{w.week}</td><td>{w.sessions}</td><td>{w.minutes}</td>
                <td>{pct(w.scores.calculation)}</td><td>{pct(w.scores.endgame)}</td><td>{pct(w.scores.guess)}</td><td>{w.pages}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="hint">{t('train.target')}</p>
      </section>

      <section className="train-method hint">
        <p>{t('train.method')}</p>
        <p>
          <a href="https://nextlevelchess.com/mastering-chess-puzzles-comprehensive-guide-to-effective-problem-solving" target="_blank" rel="noreferrer">{t('train.link.puzzles')}</a>
          {' · '}
          <a href="https://nextlevelchess.com/resources-to-improve-your-skills-for-all-levels/" target="_blank" rel="noreferrer">{t('train.link.tests')}</a>
          {' · '}
          <a href="https://nextlevelchess.com/fixing-your-skill-gap-step-by-step/" target="_blank" rel="noreferrer">{t('train.link.focus')}</a>
        </p>
      </section>
    </>
  )
}

/** The books each subject draws from: a checkbox per book and subject, automatic until changed. */
function SubjectBooks({ record, books, update }: { record: TrainerRecord; books: TrainerBook[]; update: (r: TrainerRecord) => void }) {
  const { t } = useTranslation()
  const picked = (subject: BlockKind) => record.sources[subject] ?? books.filter((b) => b.uses[subject]).map((b) => b.id)
  const toggle = (subject: BlockKind, id: string) => {
    const now = picked(subject)
    const next = now.includes(id) ? now.filter((x) => x !== id) : [...now, id]
    update({ ...record, sources: { ...record.sources, [subject]: next } })
  }
  const automatic = (subject: BlockKind) => {
    const sources = { ...record.sources }
    delete sources[subject]
    update({ ...record, sources })
  }
  const none = (subject: BlockKind) => !books.some((b) => b.material[subject] && picked(subject).includes(b.id))

  return (
    <section className="train-subjects">
      <h3>{t('train.subjects')}</h3>
      <p className="hint">{t('train.subjectsHint')}</p>
      <div className="subject-table">
        <table>
          <thead>
            <tr>
              <th>{t('train.book')}</th>
              {SUBJECTS.map((subject) => (
                <th key={subject}>
                  {t(`train.block.${subject}`)}
                  <br />
                  {record.sources[subject] ? (
                    <button type="button" className="link" onClick={() => automatic(subject)}>{t('train.backToAuto')}</button>
                  ) : (
                    <span className="hint">{t('train.auto')}</span>
                  )}
                  {books.length > 0 && none(subject) && <span className="warn"> · {t('train.noneSkipped')}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {books.map((b) => (
              <tr key={b.id}>
                <td className="title" title={b.title}>{b.title}</td>
                {SUBJECTS.map((subject) => {
                  const count = b.material[subject]
                  const what = t(`train.material.${subject === 'reading' ? b.kind : subject}`, { count })
                  return (
                    <td key={subject}>
                      {count ? (
                        <label className="check" title={what}>
                          <input
                            type="checkbox"
                            checked={picked(subject).includes(b.id)}
                            onChange={() => toggle(subject, b.id)}
                            aria-label={`${t(`train.block.${subject}`)}: ${b.title}`}
                          />
                          <span className="hint">{count}</span>
                        </label>
                      ) : (
                        <span className="hint" title={t('train.nothingFor')}>—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

// --- A session ----------------------------------------------------------------------------------

function Session({ record, current, update }: { record: TrainerRecord; current: RunningSession; update: (r: TrainerRecord) => void }) {
  const { t } = useTranslation()
  const { plan } = current
  const block = plan.blocks[current.block]
  const done = sessionDone(current)
  const next = (result: ItemResult | null) => update(advance(record, result, isoNow()))
  const [confirming, setConfirming] = useState(false)
  const cancel = () => {
    save(READING_KEY, null)
    update(cancelSession(record))
  }

  return (
    <>
      <div className="train-blocks">
        {plan.blocks.map((b, i) => (
          <span key={i} className={`chip${i === current.block ? ' active' : ''}${i < current.block ? ' done' : ''}`}>
            {i < current.block ? '✓ ' : ''}{t(`train.block.${b.kind}`)} · {b.minutes} min
          </span>
        ))}
        <span className="spacer" />
        {!done && <button type="button" onClick={() => update(skipBlock(record, isoNow()))}>{t('train.skipBlock')}</button>}
        {!done && (
          <button type="button" onClick={() => update({ ...record, current: { ...current, block: plan.blocks.length, item: 0 } })}>
            {t('train.endNow')}
          </button>
        )}
        <button type="button" className="danger-outline" onClick={() => setConfirming(true)}>{t('train.cancelSession')}</button>
      </div>
      {confirming && <ConfirmCancel current={current} onYes={cancel} onNo={() => setConfirming(false)} />}
      {done ? (
        <Summary record={record} current={current} update={update} />
      ) : (
        <BlockView key={`${current.block}:${current.item}`} block={block} current={current} onDone={next} />
      )}
    </>
  )
}

/** Asks before dropping a session: keeping it is the default (also with Escape or a click outside). */
function ConfirmCancel({ current, onYes, onNo }: { current: RunningSession; onYes: () => void; onNo: () => void }) {
  const { t } = useTranslation()
  const keep = useRef<HTMLButtonElement>(null)
  const [spent] = useState(() => Date.now() - Date.parse(current.started))
  const done = current.results.flat().length
  useEffect(() => {
    keep.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onNo()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onNo])
  return (
    <div className="modal-backdrop" onClick={onNo}>
      <div className="modal" role="alertdialog" aria-modal="true" aria-labelledby="cancel-title" aria-describedby="cancel-text" onClick={(e) => e.stopPropagation()}>
        <h3 id="cancel-title">{t('train.cancelTitle')}</h3>
        <p id="cancel-text">{t('train.cancelText', { count: done, time: formatTime(spent) })}</p>
        <p className="hint">{t('train.cancelKeeps')}</p>
        <div className="actions">
          <button type="button" ref={keep} className="primary" onClick={onNo}>{t('train.keepTraining')}</button>
          <button type="button" className="danger" onClick={onYes}>{t('train.cancelYes')}</button>
        </div>
      </div>
    </div>
  )
}

function BlockView({ block, current, onDone }: { block: PlanBlock; current: RunningSession; onDone: (r: ItemResult | null) => void }) {
  const { t } = useTranslation()
  const started = Date.parse(current.blockStarted)
  const count = block.items.length
  const heading = (
    <p className="hint">
      {t(`train.about.${block.kind}`)}
      {count > 1 && ` · ${t('train.itemOf', { n: current.item + 1, count })}`}
    </p>
  )

  if (block.kind === 'calculation') {
    const item = block.items[current.item]
    return (
      <section className="train-block">
        {heading}
        <CalcBlock item={item} minutes={block.minutes} count={count} test={current.plan.test} blockStarted={started} onDone={onDone} />
      </section>
    )
  }
  if (block.kind === 'endgame') {
    const item = block.items[current.item]
    return (
      <section className="train-block">
        {heading}
        <PlayOut item={item} onDone={(r) => onDone({ kind: 'endgame', book: item.book, key: item.key, ...r })} />
      </section>
    )
  }
  if (block.kind === 'reading') {
    return (
      <section className="train-block">
        {heading}
        <ReadingStartView item={block.items[current.item]} minutes={block.minutes} />
      </section>
    )
  }
  return (
    <section className="train-block">
      {heading}
      <GuessBlock item={block.items[current.item]} onDone={onDone} />
    </section>
  )
}

function CalcBlock(props: { item: CalcItem; minutes: number; count: number; test: boolean; blockStarted: number; onDone: (r: ItemResult) => void }) {
  const { item, onDone } = props
  // A test shares one clock for all its positions; a session gives each position its share.
  const [timeMs] = useState(() => {
    const total = props.minutes * 60000
    return props.test ? Math.max(30000, total - (Date.now() - props.blockStarted)) : total / props.count
  })
  return (
    <CalcTest
      item={item}
      timeMs={timeMs}
      feedback={!props.test}
      onDone={(r) => onDone({ kind: 'calculation', book: item.book, key: item.key, ...r })}
    />
  )
}

function GuessBlock({ item, onDone }: { item: GuessItem; onDone: (r: ItemResult) => void }) {
  const { t } = useTranslation()
  const [started] = useState(() => Date.now())
  const [game] = useState<Game>(() => {
    const nodes = item.line.map((n) => ({ ...n, refs: [] }))
    return { id: item.game, title: item.title, start_fen: nodes[0].fen, root: nodes[0].id, nodes }
  })
  const [tree] = useState(() => treeOf(item.line))
  return (
    <>
      <p className="hint">{t('train.sourceBook', { book: item.bookTitle })}</p>
      <GuessGame
        bookId={item.book}
        games={[game]}
        tree={tree}
        run={{
          from: item.from,
          moves: item.moves,
          onDone: (s) => onDone({ kind: 'guess', book: item.book, game: item.game, ...s, ms: Date.now() - started }),
        }}
      />
    </>
  )
}

/** A reading block: where to start, and the book opened there (the reader comes back with "Done"). */
function ReadingStartView({ item, minutes }: { item: ReadingItem; minutes: number }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const lastSeen = load<{ page?: number; chapter?: number }>(`pos.${item.book}`, {})
  const from = item.at ?? (item.kind === 'pdf' ? lastSeen.page : lastSeen.chapter) ?? 0
  const open = () => {
    save(`pos.${item.book}`, item.kind === 'pdf' ? { page: from } : { chapter: from })
    save(`mode.${item.book}`, 'read')
    save(READING_KEY, { book: item.book, from, started: Date.now() } satisfies ReadingStart)
    navigate(`/books/${item.book}?training=1`)
  }
  return (
    <div className="reading-start">
      <h3>{item.bookTitle}</h3>
      <p>
        {t(item.kind === 'pdf' ? 'train.fromPage' : 'train.fromChapter', { at: from + 1, of: item.length })} · {t('train.forMinutes', { minutes })}
      </p>
      <p className="hint">{t('train.readingHint')}</p>
      <button type="button" className="primary" onClick={open}>{t('train.openBook')}</button>
    </div>
  )
}

function Summary({ record, current, update }: { record: TrainerRecord; current: RunningSession; update: (r: TrainerRecord) => void }) {
  const { t } = useTranslation()
  const [focus, setFocus] = useState(7)
  const [note, setNote] = useState('')
  const [ms] = useState(() => Date.now() - Date.parse(current.started))
  const calcItems = new Map<string, CalcItem>()
  current.plan.blocks.forEach((b) => b.kind === 'calculation' && b.items.forEach((it) => calcItems.set(`${it.book}:${it.key}`, it)))
  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

  return (
    <section className="train-summary">
      <h2>{t('train.summary')}</h2>
      <p>{t('train.spent', { time: formatTime(ms) })}</p>
      <table>
        <tbody>
          {current.plan.blocks.map((b, i) => (
            <tr key={i}>
              <td>{t(`train.block.${b.kind}`)}</td>
              <td>{current.results[i].length ? pct(blockScore(current.results[i])) : t('train.skipped')}</td>
              <td className="hint">{describe(current.results[i], t)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {calcItems.size > 0 && (
        <div className="calc-review">
          <h3>{t('train.review')}</h3>
          <ol>
            {current.results.flat().filter((r) => r.kind === 'calculation').map((r, i) => {
              const it = calcItems.get(`${r.book}:${r.key}`)
              const tree = it ? treeOf(it.tree) : null
              const book = it && tree ? mainLine(tree, it.root).map((n) => n.san).join(' ') : ''
              return (
                <li key={i} className={r.result}>
                  <strong>{t(`train.grade.${r.result}`)}</strong> — {it?.bookTitle} {it?.label ? `#${it.label}` : ''}
                  <br />
                  <span className="hint">{t('train.yourLine')}: {r.line.join(' ') || '—'} · {t('train.bookLine')}: {book}</span>
                </li>
              )
            })}
          </ol>
        </div>
      )}

      <label className="focus-score">
        {t('train.focusScore', { n: focus })}
        <input type="range" min={1} max={10} value={focus} onChange={(e) => setFocus(Number(e.target.value))} />
      </label>
      <label className="session-note">
        {t('train.note')}
        <textarea value={note} rows={3} placeholder={t('train.notePlaceholder')} onChange={(e) => setNote(e.target.value)} />
      </label>
      <button type="button" className="primary" onClick={() => update(finishSession(record, focus, note.trim(), isoNow()))}>
        {t('train.save')}
      </button>
    </section>
  )
}

function describe(results: ItemResult[], t: (k: string, o?: Record<string, unknown>) => string): string {
  return results
    .map((r) => {
      if (r.kind === 'calculation') return t(`train.grade.${r.result}`)
      if (r.kind === 'endgame') return `${t(`train.goal.${r.goal}`)}: ${t(`train.play.${r.result}`)}`
      if (r.kind === 'reading') return t('train.read', { count: Math.max(0, r.to - r.from) })
      return t('guess.score', { same: r.same, good: r.good, total: r.total })
    })
    .join(' · ')
}
