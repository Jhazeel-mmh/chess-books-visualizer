import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type EpubLayout, type MarkKind } from '../api'
import { MARK_ATTR, type Target } from '../target'

interface Props {
  bookId: string
  layout: EpubLayout
  target: Target | null
  describeUnresolved: (id: string) => string
  onPick: (kind: MarkKind, id: string) => void
  onKey: (e: KeyboardEvent) => void
  /** Show move highlights (diagrams stay clickable either way). */
  highlights: boolean
  initialChapter: number
  onChapter: (chapter: number) => void
}

// Injected into each chapter: the book keeps its own styles, marks get ours.
const MARK_CSS = `
.cbv-move { cursor: pointer; border-radius: 3px; background: rgba(47, 107, 79, 0.12); }
.cbv-move:hover { background: rgba(47, 107, 79, 0.3); }
.cbv-unresolved { text-decoration: underline dotted rgba(179, 38, 30, 0.7); cursor: help; }
.cbv-move.cbv-uncertain { background: none; border-bottom: 2px dashed rgba(47, 107, 79, 0.6); }
.cbv-diagram { cursor: pointer; }
.cbv-diagram:hover { outline: 2px solid rgba(47, 107, 79, 0.6); }
.cbv-current { background: #f2c94c !important; color: #000 !important; outline: 2px solid #f2c94c; }
.cbv-plain .cbv-move { background: none; }
.cbv-plain .cbv-unresolved { text-decoration: none; }
`

export function EpubView({ bookId, layout, target, describeUnresolved, onPick, onKey, highlights, initialChapter, onChapter }: Props) {
  const { t } = useTranslation()
  const frame = useRef<HTMLIFrameElement>(null)
  const [chapter, setChapter] = useState(() => Math.min(initialChapter, layout.chapters.length - 1))
  const onChapterRef = useRef(onChapter)
  useEffect(() => {
    onChapterRef.current = onChapter
  })
  useEffect(() => onChapterRef.current(chapter), [chapter])
  const [loaded, setLoaded] = useState(-1)
  // Event listeners inside the iframe outlive renders; read the latest callbacks through a ref.
  const callbacks = useRef({ onPick, onKey, describeUnresolved })
  useEffect(() => {
    callbacks.current = { onPick, onKey, describeUnresolved }
  })

  // Follow a new target into its chapter, unless it is also printed in the open one.
  // (Reads the chapter through a ref: browsing to another chapter must not jump back.)
  const chapterRef = useRef(chapter)
  useEffect(() => {
    chapterRef.current = chapter
  })
  useEffect(() => {
    if (!target?.blocks.length) return
    const chapters = target.blocks.map((b) => layout.blocks[b])
    if (!chapters.includes(chapterRef.current)) setChapter(chapters[0])
  }, [target, layout])

  useEffect(() => {
    const doc = frame.current?.contentDocument
    if (doc && loaded === chapter) doc.documentElement.classList.toggle('cbv-plain', !highlights)
  }, [highlights, loaded, chapter])

  // Highlight the target in the loaded chapter and scroll to it if it is out of view.
  useEffect(() => {
    const doc = frame.current?.contentDocument
    if (!doc || loaded !== chapter) return
    doc.querySelectorAll('.cbv-current').forEach((el) => el.classList.remove('cbv-current'))
    if (!target) return
    const els = [...doc.querySelectorAll(`[${MARK_ATTR[target.kind]}="${CSS.escape(target.id)}"]`)]
    els.forEach((el) => el.classList.add('cbv-current'))
    const view = frame.current!.contentWindow!
    const inView = els.some((el) => {
      const r = el.getBoundingClientRect()
      return r.bottom > 0 && r.top < view.innerHeight
    })
    // Scroll the chapter's own window: scrollIntoView would also move the page around the iframe.
    if (els.length && !inView && !target.fromBook) {
      view.scrollBy({ top: els[0].getBoundingClientRect().top - view.innerHeight / 2 })
    }
  }, [target, loaded, chapter])

  const onLoad = () => {
    const doc = frame.current?.contentDocument
    if (!doc) return
    const style = doc.createElement('style')
    style.textContent = MARK_CSS
    ;(doc.head ?? doc.documentElement).appendChild(style)
    doc.querySelectorAll<HTMLElement>('[data-cbv-unresolved]').forEach((el) => {
      el.title = callbacks.current.describeUnresolved(el.dataset.cbvUnresolved!)
    })
    doc.querySelectorAll<HTMLElement>('.cbv-uncertain').forEach((el) => {
      el.title = t('reader.uncertainMove')
    })
    doc.addEventListener('click', (e) => {
      const el = (e.target as Element).closest('[data-cbv-node], [data-cbv-diagram]') as HTMLElement | null
      if (!el) return
      e.preventDefault()
      if (el.dataset.cbvNode) callbacks.current.onPick('move', el.dataset.cbvNode)
      else callbacks.current.onPick('diagram', el.dataset.cbvDiagram!)
    })
    doc.addEventListener('keydown', (e) => callbacks.current.onKey(e))
    setLoaded(chapter)
  }

  const go = (n: number) => setChapter(Math.max(0, Math.min(layout.chapters.length - 1, n)))

  return (
    <div className="epub-view">
      <div className="book-nav">
        <button type="button" onClick={() => go(chapter - 1)} disabled={chapter === 0} aria-label={t('reader.prevChapter')}>◀</button>
        <select value={chapter} onChange={(e) => go(Number(e.target.value))}>
          {layout.chapters.map((c, i) => (
            <option key={c.href} value={i}>
              {c.title ?? t('reader.chapter', { n: i + 1 })}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => go(chapter + 1)}
          disabled={chapter === layout.chapters.length - 1}
          aria-label={t('reader.nextChapter')}
        >
          ▶
        </button>
      </div>
      <iframe
        ref={frame}
        key={chapter}
        className="book-frame"
        title={layout.chapters[chapter]?.title ?? ''}
        src={api.epubUrl(bookId, layout.chapters[chapter].href)}
        sandbox="allow-same-origin"
        onLoad={onLoad}
      />
    </div>
  )
}
