import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, type Analysis, type BookMeta, type Diagram, type Layout, type MarkKind, type MoveFix, type MoveNode } from '../api'
import { BoardPanel, type Step } from '../components/BoardPanel'
import { BookToolbar } from '../components/BookToolbar'
import { DiagramEditor } from '../components/DiagramEditor'
import { EpubView } from '../components/EpubView'
import { MoveFixer } from '../components/MoveFixer'
import { PdfView, type FixBox } from '../components/PdfView'
import { TrainingBar } from '../components/TrainingBar'
import { moveBefore } from '../fixMoves'
import { load, save } from '../storage'
import type { Target } from '../target'
import type { BookTarget } from './Solver'

// Solving mode (and its chess logic) loads only when it is used.
const Solver = lazy(() => import('./Solver'))
type Mode = 'read' | 'solve'

const KEYS: Record<string, Step> = { ArrowLeft: 'prev', ArrowRight: 'next', Home: 'start', End: 'end' }
const busy = (b?: BookMeta) => b?.status === 'queued' || b?.status === 'analyzing'

export function Reader() {
  const { id = '' } = useParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const book = useQuery({
    queryKey: ['book', id],
    queryFn: () => api.book(id),
    refetchInterval: (q) => (busy(q.state.data) ? 1500 : false),
  })
  // A book disabled after a copyright notice can't be opened: nothing of it loads.
  const ready = book.data?.status === 'ready' && !book.data.disabled
  // While a correction is being applied the last analysis stays on screen.
  const analysis = useQuery({ queryKey: ['analysis', id], queryFn: () => api.analysis(id), enabled: ready })
  const layout = useQuery({ queryKey: ['layout', id], queryFn: () => api.layout(id), enabled: ready })

  const wasBusy = useRef(false)
  useEffect(() => {
    if (busy(book.data)) wasBusy.current = true
    else if (ready && wasBusy.current) {
      wasBusy.current = false
      for (const key of ['analysis', 'layout', 'marks']) queryClient.invalidateQueries({ queryKey: [key, id] })
    }
  }, [book.data, ready, id, queryClient])

  // Reading or solving, remembered per book. "Open in the book" from solving comes back to a place.
  const [mode, setMode] = useState<Mode>(() => load(`mode.${id}`, 'read'))
  const [opening, setOpening] = useState<BookTarget | null>(null)
  const switchMode = (m: Mode) => {
    setMode(m)
    save(`mode.${id}`, m)
    if (m === 'solve') setOpening(null)
  }
  // Opened from the trainer for a reading block.
  const [params] = useSearchParams()
  const training = params.has('training')
  const canSolve = !!analysis.data && (analysis.data.diagrams.some((d) => d.problem) || analysis.data.games.some((g) => g.nodes.length > 12))
  const solving = mode === 'solve' && canSolve

  return (
    <main className="reader">
      {training && <TrainingBar bookId={id} kind={layout.data?.kind} />}
      <div className="reader-bar">
        <Link to="/">← {t('reader.back')}</Link>
        <h2>{book.data?.title}</h2>
        {canSolve && (
          <div className="modes" role="tablist" aria-label={t('mode.label')}>
            <button type="button" role="tab" aria-selected={!solving} className={!solving ? 'active' : ''} onClick={() => switchMode('read')}>
              {t('mode.read')}
            </button>
            <button type="button" role="tab" aria-selected={solving} className={solving ? 'active' : ''} onClick={() => switchMode('solve')}>
              {t('mode.solve')}
            </button>
          </div>
        )}
        {analysis.data && !solving && <Coverage analysis={analysis.data} />}
        {busy(book.data) && analysis.data && <span className="badge busy">{t('reader.updating')}</span>}
      </div>
      {book.data?.disabled && <p className="notice">{t('reader.disabled')}</p>}
      {book.data && !book.data.disabled && !ready && !analysis.data && <p className="notice">{t('reader.notReady')}</p>}
      {analysis.data && solving && (
        <Suspense fallback={<p className="notice">{t('mode.loading')}</p>}>
          <Solver
            bookId={id}
            analysis={analysis.data}
            onOpenInBook={(target) => {
              setOpening(target)
              switchMode('read')
            }}
          />
        </Suspense>
      )}
      {analysis.data && layout.data && !solving && (
        <ReaderBody bookId={id} analysis={analysis.data} layout={layout.data} opening={opening} />
      )}
    </main>
  )
}

function Coverage({ analysis }: { analysis: Analysis }) {
  const { t } = useTranslation()
  const { moves_found, moves_resolved, diagrams = 0, diagrams_read = 0 } = analysis.stats
  const pct = moves_found ? Math.round((100 * moves_resolved) / moves_found) : 0
  return (
    <>
      <span className="badge">{t('reader.linked', { pct })}</span>
      {diagrams > 0 && <span className="badge">{t('reader.diagramsRead', { read: diagrams_read, total: diagrams })}</span>}
    </>
  )
}

interface Position {
  page?: number
  chapter?: number
}

interface BodyProps {
  bookId: string
  analysis: Analysis
  layout: Layout
  /** A place to show first (coming back from solving mode). */
  opening: BookTarget | null
}

/** The selection that shows a place in the book: a move (and its game), or a diagram not linked to moves. */
function openingAt(opening: BookTarget | null, nodeIndex: Map<string, { game: number; node: MoveNode }>, diagrams: Map<string, Diagram>) {
  if (!opening) return null
  const d = opening.kind === 'diagram' ? diagrams.get(opening.id) : undefined
  const nodeId = opening.kind === 'node' ? opening.id : (d?.node ?? undefined)
  const hit = nodeId ? nodeIndex.get(nodeId) : undefined
  const target: Target | null = d
    ? { kind: 'diagram', id: d.id, blocks: [d.block] }
    : hit && hit.node.refs.length
      ? { kind: 'move', id: nodeId!, blocks: hit.node.refs.map((r) => r[0]) }
      : null
  return { game: hit?.game ?? 0, node: hit ? nodeId : undefined, diagram: d && !d.node ? d.id : null, target }
}

function ReaderBody({ bookId, analysis, layout, opening }: BodyProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const nodeIndex = useMemo(() => {
    const m = new Map<string, { game: number; node: MoveNode }>()
    analysis.games.forEach((g, gi) => g.nodes.forEach((n) => m.set(n.id, { game: gi, node: n })))
    return m
  }, [analysis])
  const diagrams = useMemo(() => new Map(analysis.diagrams.map((d) => [d.id, d])), [analysis])
  const diagramOfNode = useMemo(
    () => new Map(analysis.diagrams.filter((d) => d.node).map((d) => [d.node!, d])),
    [analysis],
  )

  // Reading position and view settings, remembered between visits.
  const saved = useMemo(() => load<Position>(`pos.${bookId}`, {}), [bookId])
  const [page, setPage] = useState(saved.page ?? 0)
  const [chapter, setChapter] = useState(saved.chapter ?? 0)
  const [jump, setJump] = useState<{ page: number } | null>(() => (saved.page ? { page: saved.page } : null))
  const [zoom, setZoom] = useState(() => load('zoom', 1))
  const [highlights, setHighlights] = useState(() => load('highlights', true))
  // The layout: board panel width (dragging the divider), on which side, and Focus (board only).
  const [view, setView] = useState<View>(() => load('readerView', DEFAULT_VIEW))
  useEffect(() => save('readerView', view), [view])
  // Diagram navigation can visit only the diagrams worth checking (doubtful readings and the like).
  const [checkOnly, setCheckOnly] = useState(false)
  const toCheck = useMemo(() => analysis.diagrams.filter(needsCheck), [analysis])
  useEffect(() => {
    const timer = setTimeout(() => save(`pos.${bookId}`, layout.kind === 'pdf' ? { page } : { chapter }), 500)
    return () => clearTimeout(timer)
  }, [bookId, layout.kind, page, chapter])
  useEffect(() => save('zoom', zoom), [zoom])
  useEffect(() => save('highlights', highlights), [highlights])

  // Coming back from solving mode, the reader starts at the problem's solution (or its diagram).
  const [initial] = useState(() => openingAt(opening, nodeIndex, diagrams))
  const [gameIndex, setGameIndex] = useState(initial?.game ?? 0)
  const game = analysis.games[gameIndex]
  const byId = useMemo(() => new Map(game?.nodes.map((n) => [n.id, n])), [game])
  const [nodeId, setNodeId] = useState(initial?.node ?? game?.root)
  const node = (nodeId && byId.get(nodeId)) || (game && byId.get(game.root))
  const [diagramId, setDiagramId] = useState<string | null>(initial?.diagram ?? null)
  const [target, setTarget] = useState<Target | null>(initial?.target ?? null)
  const [editing, setEditing] = useState(false)
  // Fixing moves on the pages (PDF books).
  const [fixing, setFixing] = useState(false)

  const selectNode = useCallback(
    (id: string, fromBook = false) => {
      const hit = nodeIndex.get(id)
      if (!hit) return
      setGameIndex(hit.game)
      setNodeId(id)
      setDiagramId(null)
      setEditing(false)
      const shownBy = diagramOfNode.get(id)
      if (hit.node.refs.length) setTarget({ kind: 'move', id, blocks: hit.node.refs.map((r) => r[0]), fromBook })
      else if (shownBy) setTarget({ kind: 'diagram', id: shownBy.id, blocks: [shownBy.block], fromBook })
      else setTarget(null)
    },
    [nodeIndex, diagramOfNode],
  )

  const selectDiagram = useCallback(
    (id: string, fromBook = false) => {
      const d = diagrams.get(id)
      if (!d) return
      if (d.node) selectNode(d.node, fromBook)
      else {
        setDiagramId(id)
        setEditing(false)
      }
      setTarget({ kind: 'diagram', id, blocks: [d.block], fromBook })
    },
    [diagrams, selectNode],
  )

  const pick = (kind: MarkKind, id: string) => (kind === 'move' ? selectNode(id, true) : selectDiagram(id, true))


  const selectGame = (index: number) => selectNode(analysis.games[index].root)

  // While the reader explores moves on the board, the arrow keys step through those.
  const exploreKeys = useRef<((to: Step) => boolean) | null>(null)
  const setExploreKeys = useCallback((stepper: ((to: Step) => boolean) | null) => {
    exploreKeys.current = stepper
  }, [])
  const step = useCallback(
    (to: Step) => {
      if (exploreKeys.current?.(to)) return
      if (!game || !node) return
      let next = node
      if (to === 'start') next = byId.get(game.root)!
      if (to === 'prev' && node.parent) next = byId.get(node.parent)!
      if (to === 'next' && node.children.length) next = byId.get(node.children[0])!
      if (to === 'end') while (next.children.length) next = byId.get(next.children[0])!
      selectNode(next.id)
    },
    [game, node, byId, selectNode],
  )

  // Where "next diagram" counts from: the selection if it is where the reader is, else the open page.
  const readingBlock = () => {
    const here = layout.kind === 'pdf' ? page : chapter
    const first = target?.blocks[0]
    if (first !== undefined && Math.abs(layout.blocks[first] - here) <= 1) return first
    const start = layout.blocks.findIndex((p) => p >= here)
    return start < 0 ? layout.blocks.length : start - 0.5
  }
  const nextDiagram = (dir: 1 | -1) => {
    const from = readingBlock()
    const list = checkOnly ? toCheck : analysis.diagrams
    const d = dir > 0 ? list.find((x) => x.block > from) : list.findLast((x) => x.block < from)
    if (d) selectDiagram(d.id)
  }
  const goToLabel = (label: string) => {
    const matches = analysis.diagrams.filter((d) => d.label === label)
    if (!matches.length) return false
    const from = readingBlock()
    selectDiagram((matches.find((d) => d.block > from) ?? matches[0]).id)
    return true
  }

  const nextDiagramRef = useRef(nextDiagram)
  useEffect(() => {
    nextDiagramRef.current = nextDiagram
  })
  const onKey = useCallback(
    (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest?.('input, select, textarea') || editing || fixing) return
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        setView((v) => ({ ...v, focus: !v.focus }))
      } else if (e.key === '[' || e.key === ']') {
        e.preventDefault()
        nextDiagramRef.current(e.key === ']' ? 1 : -1)
      } else if (KEYS[e.key]) {
        e.preventDefault()
        step(KEYS[e.key])
      }
    },
    [step, editing, fixing],
  )
  const onKeyRef = useRef(onKey)
  useEffect(() => {
    onKeyRef.current = onKey
  })
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKeyRef.current(e)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  const describeUnresolved = useCallback(
    (id: string) => {
      const u = analysis.unresolved[Number(id)]
      return u ? `${u.text} — ${t(`reader.reason.${u.reason}`)}` : ''
    },
    [analysis, t],
  )
  const showUnresolved = (i: number) =>
    setTarget({ kind: 'unresolved', id: String(i), blocks: analysis.unresolved[i].refs.map((r) => r[0]) })

  // The diagram behind what the board shows, if any: an unlinked diagram, or the one showing this position.
  const unlinked = diagramId ? diagrams.get(diagramId) : undefined
  const shown: Diagram | undefined = unlinked ?? (node ? diagramOfNode.get(node.id) : undefined)
  const rootDiagram = game ? diagramOfNode.get(game.root) : undefined
  const toSolution = shown?.node && byId.get(shown.node)?.children.length ? () => selectNode(byId.get(shown.node!)!.children[0]) : undefined
  const toDiagram = rootDiagram && node && node.id !== game?.root ? () => selectDiagram(rootDiagram.id) : undefined

  const bodyRef = useRef<HTMLDivElement>(null)
  const startSplit = (e: ReactPointerEvent<HTMLElement>) => {
    const body = bodyRef.current
    if (!body) return
    e.preventDefault()
    const handle = e.currentTarget
    handle.setPointerCapture(e.pointerId)
    const move = (ev: PointerEvent) => {
      const rect = body.getBoundingClientRect()
      const width = view.side === 'right' ? rect.right - ev.clientX : ev.clientX - rect.left
      setView((v) => ({ ...v, panel: Math.round(Math.max(MIN_PANEL, Math.min(rect.width - MIN_BOOK, width))) }))
    }
    const end = () => {
      handle.removeEventListener('pointermove', move)
      handle.removeEventListener('pointerup', end)
    }
    handle.addEventListener('pointermove', move)
    handle.addEventListener('pointerup', end)
  }

  // Fixing moves on the pages: the place picked, and the move it most likely follows.
  const [fixBox, setFixBox] = useState<FixBox | null>(null)
  const [fixBase, setFixBase] = useState<MoveNode | null>(null)
  const allNodes = useMemo(() => new Map([...nodeIndex].map(([nid, hit]) => [nid, hit.node])), [nodeIndex])
  const moveFixes = useQuery({ queryKey: ['moveFixes', bookId], queryFn: () => api.moveFixes(bookId), enabled: fixing })
  const marksOf = (p: number) =>
    queryClient.fetchQuery({ queryKey: ['marks', bookId, p], queryFn: () => api.pageMarks(bookId, p), staleTime: Infinity })
  const pickFixBox = async (box: FixBox) => {
    setFixBox(box)
    if (box.mark?.kind === 'move') {
      // A wrong link: the fix replaces it, from the position before it.
      const parent = allNodes.get(box.mark.id)?.parent
      setFixBase((parent && allNodes.get(parent)) || null)
      return
    }
    let found = moveBefore(await marksOf(box.page), box.rect)
    for (let p = box.page - 1; !found && p >= Math.max(0, box.page - 3); p--) {
      found = moveBefore(await marksOf(p), [0, 1e6, 1e6, 1e6 + 1])
    }
    setFixBase((found && allNodes.get(found)) || node || null)
  }
  const saveFixes = useMutation({
    mutationFn: (fixes: MoveFix[]) => api.saveMoveFixes(bookId, fixes),
    onSuccess: () => {
      setFixBox(null)
      queryClient.invalidateQueries({ queryKey: ['moveFixes', bookId] })
      queryClient.invalidateQueries({ queryKey: ['book', bookId] })
    },
  })

  const correction = useMutation({
    mutationFn: (fix: { placement: string; turn: 'w' | 'b' }) => api.correctDiagram(bookId, shown!.key!, fix.placement, fix.turn),
    onSuccess: () => {
      setEditing(false)
      queryClient.invalidateQueries({ queryKey: ['book', bookId] })
    },
  })

  return (
    <div
      ref={bodyRef}
      className={`reader-body board-${view.side}${view.focus ? ' focus' : ''}`}
      style={{ '--panel-width': `${view.panel}px` } as CSSProperties}
    >
      <section className="book-view">
        <BookToolbar
          layout={layout}
          page={page}
          onGoToPage={(p) => setJump({ page: p })}
          zoom={zoom}
          onZoom={setZoom}
          onPrevDiagram={() => nextDiagram(-1)}
          onNextDiagram={() => nextDiagram(1)}
          onGoToLabel={goToLabel}
          highlights={highlights}
          onHighlights={setHighlights}
          toCheck={toCheck.length}
          checkOnly={checkOnly}
          onCheckOnly={setCheckOnly}
          fixing={fixing}
          onFixing={(on) => {
            setFixing(on)
            setFixBox(null)
          }}
        />
        {layout.kind === 'epub' ? (
          <EpubView
            bookId={bookId}
            layout={layout}
            target={target}
            describeUnresolved={describeUnresolved}
            onPick={pick}
            onKey={onKey}
            highlights={highlights}
            initialChapter={saved.chapter ?? 0}
            onChapter={setChapter}
          />
        ) : (
          <PdfView
            bookId={bookId}
            layout={layout}
            target={target}
            describeUnresolved={describeUnresolved}
            onPick={pick}
            zoom={zoom}
            highlights={highlights}
            jump={jump}
            onPage={setPage}
            fixing={fixing ? { box: fixBox, onPickBox: pickFixBox } : undefined}
          />
        )}
      </section>
      <div className="splitter" role="separator" aria-orientation="vertical" aria-label={t('board.splitter')} title={t('board.splitter')} onPointerDown={startSplit} />
      {fixing ? (
        <MoveFixer
          box={fixBox}
          base={fixBase}
          byId={allNodes}
          fixes={moveFixes.data ?? []}
          saving={saveFixes.isPending}
          onSave={(fixes) => saveFixes.mutate(fixes)}
          onGoTo={(p) => setJump({ page: p })}
          onCancel={() => setFixBox(null)}
          onClose={() => {
            setFixing(false)
            setFixBox(null)
          }}
        />
      ) : editing && shown?.key ? (
        <aside className="board-panel">
          <DiagramEditor
            placement={shown.placement ?? '8/8/8/8/8/8/8/8'}
            turn={shown.turn ?? (node && !unlinked ? (node.fen.split(' ')[1] as 'w' | 'b') : 'w')}
            uncertain={shown.uncertain ?? []}
            saving={correction.isPending}
            onSave={(placement, turn) => correction.mutate({ placement, turn })}
            onCancel={() => setEditing(false)}
          />
        </aside>
      ) : (
        <BoardPanel
          bookId={bookId}
          games={analysis.games}
          game={game}
          byId={byId}
          node={node}
          diagram={unlinked}
          shown={shown}
          onEdit={shown?.key ? () => setEditing(true) : undefined}
          onToSolution={toSolution}
          onToDiagram={toDiagram}
          onSelectGame={selectGame}
          onSelect={(id) => selectNode(id)}
          onStep={step}
          onExploreKeys={setExploreKeys}
          focus={view.focus}
          onFocus={() => setView({ ...view, focus: !view.focus })}
          onSwapSide={() => setView({ ...view, side: view.side === 'right' ? 'left' : 'right' })}
        >
          <Unresolved analysis={analysis} onShow={showUnresolved} />
        </BoardPanel>
      )}
    </div>
  )
}

interface View {
  /** Width of the board panel, in pixels. */
  panel: number
  side: 'left' | 'right'
  /** Only the board panel, wide: for small screens. */
  focus: boolean
}
const DEFAULT_VIEW: View = { panel: 440, side: 'right', focus: false }
const MIN_PANEL = 300
const MIN_BOOK = 320

/** A diagram with a reason to doubt its reading (a correction made from the solution counts too). */
const needsCheck = (d: Diagram) => d.to_check ?? false

function Unresolved({ analysis, onShow }: { analysis: Analysis; onShow: (i: number) => void }) {
  const { t } = useTranslation()
  if (!analysis.unresolved.length) return null
  const shown = analysis.unresolved.slice(0, 500)
  return (
    <details className="unresolved">
      <summary>{t('reader.unresolved', { count: analysis.unresolved.length })}</summary>
      <ul>
        {shown.map((u, i) => (
          <li key={i}>
            <button type="button" className="link" onClick={() => onShow(i)}>
              <code>{u.text}</code>
            </button>{' '}
            — {t(`reader.reason.${u.reason}`)}
          </li>
        ))}
      </ul>
      {analysis.unresolved.length > shown.length && (
        <p className="hint">{t('reader.moreUnresolved', { count: analysis.unresolved.length - shown.length })}</p>
      )}
    </details>
  )
}
