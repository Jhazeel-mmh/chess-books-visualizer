import { useQuery } from '@tanstack/react-query'
import { memo, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type MarkKind, type PdfLayout } from '../api'
import { scrollWithin } from '../scroll'
import type { Target } from '../target'

interface Props {
  bookId: string
  layout: PdfLayout
  target: Target | null
  describeUnresolved: (id: string) => string
  onPick: (kind: MarkKind, id: string) => void
  /** Page width relative to the view (1 = fit width). */
  zoom: number
  /** Show move highlights (diagrams stay clickable either way). */
  highlights: boolean
  /** Scroll request: a new object each time. */
  jump: { page: number } | null
  /** The page at the top of the view, reported while scrolling. */
  onPage: (page: number) => void
  /** Fixing moves: the box picked so far, and what to do with a new pick. */
  fixing?: { box: FixBox | null; onPickBox: (box: FixBox) => void }
}

/** Where a move is printed, picked by the reader to fix it: a mark of the app's, or a box drawn on the page. */
export interface FixBox {
  page: number
  rect: [number, number, number, number]
  mark?: { kind: MarkKind; id: string }
}

export function PdfView({ bookId, layout, target, describeUnresolved, onPick, zoom, highlights, jump, onPage, fixing }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const onPageRef = useRef(onPage)
  useEffect(() => {
    onPageRef.current = onPage
  })

  // Report the page at the top third of the view while scrolling.
  useEffect(() => {
    const root = scroller.current
    if (!root) return
    let frame = 0
    const update = () => {
      frame = 0
      const pages = root.querySelectorAll<HTMLElement>('[data-page]')
      const line = root.scrollTop + root.clientHeight / 3
      let lo = 0
      let hi = pages.length - 1
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1
        if (pages[mid].offsetTop <= line) lo = mid
        else hi = mid - 1
      }
      onPageRef.current(lo)
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    root.addEventListener('scroll', onScroll, { passive: true })
    return () => root.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    const root = scroller.current
    const el = jump && root?.querySelector(`[data-page="${jump.page}"]`)
    if (root && el) scrollWithin(root, el, 'start')
  }, [jump])

  // Bring the target's page into view unless one of its pages already is.
  useEffect(() => {
    const root = scroller.current
    if (!root || !target?.blocks.length || target.fromBook) return
    const pages = [...new Set(target.blocks.map((b) => layout.blocks[b]))]
    const box = root.getBoundingClientRect()
    const els = pages.map((p) => root.querySelector<HTMLElement>(`[data-page="${p}"]`)).filter((el) => el !== null)
    const visible = els.some((el) => {
      const r = el.getBoundingClientRect()
      return r.bottom > box.top && r.top < box.bottom
    })
    if (!visible && els[0]) scrollWithin(root, els[0], 'start')
  }, [target, layout])

  return (
    <div className={`pdf-view${highlights ? '' : ' plain'}${fixing ? ' fixing' : ''}`} ref={scroller}>
      {layout.pages.map(([w, h], n) => (
        <PdfPage
          key={n}
          bookId={bookId}
          page={n}
          width={w}
          height={h}
          zoom={zoom}
          root={scroller}
          target={target}
          describeUnresolved={describeUnresolved}
          onPick={onPick}
          fixing={fixing}
        />
      ))}
    </div>
  )
}

interface PageProps {
  bookId: string
  page: number
  width: number
  height: number
  zoom: number
  root: React.RefObject<HTMLDivElement | null>
  target: Target | null
  describeUnresolved: (id: string) => string
  onPick: (kind: MarkKind, id: string) => void
  fixing?: Props['fixing']
}

const PdfPage = memo(function PdfPage({ bookId, page, width, height, zoom, root, target, describeUnresolved, onPick, fixing }: PageProps) {
  const { t } = useTranslation()
  const uncertainTitle = t('reader.uncertainMove')
  const fixedTitle = t('fix.yours')
  const el = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(false)

  // Load the page image and its marks only once it comes near the viewport.
  useEffect(() => {
    if (!el.current) return
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setNear(true)
          observer.disconnect()
        }
      },
      { root: root.current, rootMargin: '800px 0px' },
    )
    observer.observe(el.current)
    return () => observer.disconnect()
  }, [root])

  const marks = useQuery({
    queryKey: ['marks', bookId, page],
    queryFn: () => api.pageMarks(bookId, page),
    enabled: near,
    staleTime: Infinity,
  })

  // Scroll the highlighted mark into view once this page has it.
  useEffect(() => {
    if (!target || target.fromBook || !marks.data || !el.current) return
    const mark = el.current.querySelector<HTMLElement>('.mark.current')
    const container = root.current
    if (!mark || !container) return
    const box = container.getBoundingClientRect()
    const r = mark.getBoundingClientRect()
    if (r.top < box.top || r.bottom > box.bottom || r.left < box.left || r.right > box.right) scrollWithin(container, mark)
  }, [target, marks.data, root])

  // Fixing moves: a box dragged on the page (in PDF points), shown while it is being drawn.
  const [drag, setDrag] = useState<[number, number, number, number] | null>(null)
  const toPoints = (e: { clientX: number; clientY: number }): [number, number] => {
    const r = el.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * width, ((e.clientY - r.top) / r.height) * height]
  }
  const startBox = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!fixing || (e.target as HTMLElement).classList.contains('mark')) return
    e.preventDefault()
    const [x, y] = toPoints(e)
    setDrag([x, y, x, y])
    e.currentTarget.setPointerCapture(e.pointerId)
  }
  const moveBox = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!drag) return
    const [x, y] = toPoints(e)
    setDrag([drag[0], drag[1], x, y])
  }
  const endBox = () => {
    if (!drag || !fixing) return
    const rect: [number, number, number, number] = [
      Math.min(drag[0], drag[2]), Math.min(drag[1], drag[3]), Math.max(drag[0], drag[2]), Math.max(drag[1], drag[3]),
    ]
    setDrag(null)
    if (rect[2] - rect[0] > 4 && rect[3] - rect[1] > 4) fixing.onPickBox({ page, rect })
  }
  const pickMark = (kind: MarkKind, id: string, rects: [number, number, number, number][]) =>
    fixing?.onPickBox({
      page,
      mark: { kind, id },
      rect: [Math.min(...rects.map((r) => r[0])), Math.min(...rects.map((r) => r[1])), Math.max(...rects.map((r) => r[2])), Math.max(...rects.map((r) => r[3]))],
    })
  const shownBox = drag ?? (fixing?.box?.page === page ? fixing.box.rect : null)

  const pct = (v: number, of: number) => `${(100 * v) / of}%`
  return (
    <div
      className="pdf-page"
      data-page={page}
      ref={el}
      style={{ aspectRatio: `${width} / ${height}`, width: `${zoom * 100}%` }}
      onPointerDown={startBox}
      onPointerMove={moveBox}
      onPointerUp={endBox}
    >
      {near && <img src={api.pageUrl(bookId, page)} alt="" draggable={false} />}
      {marks.data?.map((m) =>
        m.rects.map(([x0, y0, x1, y1], i) => {
          const current = target?.kind === m.kind && target.id === m.id
          const pickable = fixing && m.kind !== 'diagram'
          return (
            <span
              key={`${m.kind}${m.id}-${i}`}
              className={`mark ${m.kind}${m.uncertain ? ' uncertain' : ''}${m.fixed ? ' fixed' : ''}${current ? ' current' : ''}`}
              style={{ left: pct(x0, width), top: pct(y0, height), width: pct(x1 - x0, width), height: pct(y1 - y0, height) }}
              title={m.kind === 'unresolved' ? describeUnresolved(m.id) : m.fixed ? fixedTitle : m.uncertain ? uncertainTitle : undefined}
              onClick={pickable ? () => pickMark(m.kind, m.id, m.rects) : m.kind === 'unresolved' ? undefined : () => onPick(m.kind, m.id)}
            />
          )
        }),
      )}
      {shownBox && (
        <span
          className="fix-box"
          style={{
            left: pct(Math.min(shownBox[0], shownBox[2]), width),
            top: pct(Math.min(shownBox[1], shownBox[3]), height),
            width: pct(Math.abs(shownBox[2] - shownBox[0]), width),
            height: pct(Math.abs(shownBox[3] - shownBox[1]), height),
          }}
        />
      )}
    </div>
  )
})
