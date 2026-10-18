import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Layout } from '../api'

interface Props {
  layout: Layout
  page: number
  onGoToPage: (page: number) => void
  zoom: number
  onZoom: (zoom: number) => void
  onPrevDiagram: () => void
  onNextDiagram: () => void
  /** Jumps to the diagram printed with this number; false if there is none. */
  onGoToLabel: (label: string) => boolean
  highlights: boolean
  onHighlights: (on: boolean) => void
  /** How many diagrams are worth checking, and whether diagram navigation only visits those. */
  toCheck: number
  checkOnly: boolean
  onCheckOnly: (on: boolean) => void
  /** Fixing moves on the pages (PDF books): on or off. */
  fixing?: boolean
  onFixing?: (on: boolean) => void
}

const ZOOMS = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 2]

/** Page, zoom, contents and diagram navigation above the book. */
export function BookToolbar(props: Props) {
  const { t } = useTranslation()
  const { layout, page, onGoToPage, zoom, onZoom } = props
  // What the reader is typing in the page box; the current page otherwise.
  const [draft, setDraft] = useState<string | null>(null)
  const [label, setLabel] = useState('')
  const [notFound, setNotFound] = useState(false)

  const pdf = layout.kind === 'pdf' ? layout : null
  const zoomIndex = ZOOMS.indexOf(zoom)
  const goToPage = () => {
    const n = Number(draft)
    if (draft !== null && pdf && n >= 1 && n <= pdf.pages.length) onGoToPage(n - 1)
    setDraft(null)
  }

  return (
    <div className="book-toolbar">
      {pdf && (
        <div className="group">
          <button type="button" onClick={() => onGoToPage(Math.max(0, page - 1))} disabled={page === 0} title={t('reader.prevPage')} aria-label={t('reader.prevPage')}>◀</button>
          <input
            className="page-input"
            value={draft ?? String(page + 1)}
            inputMode="numeric"
            aria-label={t('reader.page')}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && goToPage()}
            onBlur={goToPage}
          />
          <span className="hint">/ {pdf.pages.length}</span>
          <button type="button" onClick={() => onGoToPage(Math.min(pdf.pages.length - 1, page + 1))} disabled={page >= pdf.pages.length - 1} title={t('reader.nextPage')} aria-label={t('reader.nextPage')}>▶</button>
        </div>
      )}
      {pdf && (
        <div className="group">
          <button type="button" onClick={() => onZoom(ZOOMS[Math.max(0, zoomIndex - 1)])} disabled={zoomIndex <= 0} title={t('reader.zoomOut')} aria-label={t('reader.zoomOut')}>−</button>
          <button type="button" onClick={() => onZoom(1)} title={t('reader.fitWidth')}>{Math.round(zoom * 100)}%</button>
          <button type="button" onClick={() => onZoom(ZOOMS[Math.min(ZOOMS.length - 1, zoomIndex + 1)])} disabled={zoomIndex >= ZOOMS.length - 1} title={t('reader.zoomIn')} aria-label={t('reader.zoomIn')}>+</button>
        </div>
      )}
      {pdf?.toc && pdf.toc.length > 0 && (
        <select className="toc" value="" onChange={(e) => e.target.value && onGoToPage(Number(e.target.value))} aria-label={t('reader.contents')}>
          <option value="">{t('reader.contents')}</option>
          {pdf.toc.map(([level, title, p], i) => (
            <option key={i} value={p}>
              {' '.repeat((level - 1) * 3)}
              {title}
            </option>
          ))}
        </select>
      )}
      <div className="group">
        <button type="button" onClick={props.onPrevDiagram} title={t('reader.prevDiagram')} aria-label={t('reader.prevDiagram')}>◀ ♟</button>
        <input
          className={`label-input${notFound ? ' invalid' : ''}`}
          value={label}
          placeholder={t('reader.diagramNo')}
          aria-label={t('reader.goToDiagram')}
          title={notFound ? t('reader.noSuchDiagram') : t('reader.goToDiagram')}
          onChange={(e) => {
            setLabel(e.target.value)
            setNotFound(false)
          }}
          onKeyDown={(e) => e.key === 'Enter' && label.trim() && setNotFound(!props.onGoToLabel(label.trim()))}
        />
        <button type="button" onClick={props.onNextDiagram} title={t('reader.nextDiagram')} aria-label={t('reader.nextDiagram')}>♟ ▶</button>
      </div>
      {props.toCheck > 0 && (
        <label className="check" title={t('reader.checkOnlyHint')}>
          <input type="checkbox" checked={props.checkOnly} onChange={(e) => props.onCheckOnly(e.target.checked)} />
          {t('reader.checkOnly', { count: props.toCheck })}
        </label>
      )}
      <label className="check">
        <input type="checkbox" checked={props.highlights} onChange={(e) => props.onHighlights(e.target.checked)} />
        {t('reader.highlights')}
      </label>
      {pdf && props.onFixing && (
        <button type="button" className={props.fixing ? 'active' : ''} aria-pressed={!!props.fixing} onClick={() => props.onFixing!(!props.fixing)} title={t('fix.switchHint')}>
          ✎ {t('fix.switch')}
        </button>
      )}
    </div>
  )
}
