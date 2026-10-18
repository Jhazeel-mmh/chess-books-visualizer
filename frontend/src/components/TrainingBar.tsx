import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { formatTime, isoNow } from '../progress'
import { load } from '../storage'
import { advance } from '../trainer'
import { READING_KEY, useTrainer, type ReadingStart } from '../trainerStore'

/** Shown in the book during a training session's reading block: the time left, and "Done". */
export function TrainingBar({ bookId, kind }: { bookId: string; kind: 'pdf' | 'epub' | undefined }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { record, update } = useTrainer()
  const [start] = useState(() => load<ReadingStart | null>(READING_KEY, null))
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const cur = record?.current
  const block = cur?.plan.blocks[cur.block]
  const reading = block?.kind === 'reading' && start?.book === bookId ? block : null
  if (!reading || !start || !record) {
    return (
      <div className="training-bar">
        <Link to="/train">← {t('train.backToTraining')}</Link>
      </div>
    )
  }
  const left = reading.minutes * 60000 - (now - start.started)
  const done = () => {
    const pos = load<{ page?: number; chapter?: number }>(`pos.${bookId}`, {})
    const at = (kind === 'epub' ? pos.chapter : pos.page) ?? start.from
    const result = { kind: 'reading' as const, book: bookId, from: start.from, to: Math.max(at, start.from), ms: now - start.started }
    update(advance(record, result, isoNow()))
    navigate('/train')
  }
  return (
    <div className={`training-bar${left <= 0 ? ' over' : ''}`}>
      <strong>{t('train.readingBlock')}</strong>
      <span className="clock">{left > 0 ? formatTime(left) : t('train.timeUp')}</span>
      <span className="hint">{t('train.readingDoneHint')}</span>
      <button type="button" className="primary" onClick={done}>{t('train.doneReading')}</button>
    </div>
  )
}
