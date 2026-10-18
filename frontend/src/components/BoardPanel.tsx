import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Diagram, type Game, type MoveNode } from '../api'
import { exploreMove, isPlayable, type ExploreMove } from '../explore'
import { displaySan, lineNumbers } from '../notation'
import { load, save } from '../storage'
import { positionKey, useUserData, type Annotations } from '../userData'
import { Board } from './Board'
import { BoardFrame } from './BoardFrame'
import { EngineLine } from './EngineLine'
import { useEngineSwitch } from '../useEngineSwitch'
import { MoveTree } from './MoveTree'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const EMPTY_FEN = '8/8/8/8/8/8/8/8 w - - 0 1'
const NO_ANNOTATIONS: Annotations = {}

export type Step = 'start' | 'prev' | 'next' | 'end'

/** Trying moves on the board from the book's position. */
interface Exploring {
  /** The book's position it started from. */
  base: string
  moves: ExploreMove[]
  /** How many of the moves are on the board (stepping back keeps the later ones). */
  at: number
}

interface Props {
  bookId: string
  games: Game[]
  game?: Game
  byId: Map<string, MoveNode>
  node?: MoveNode
  /** A diagram not linked to any move: shown instead of the current move's position. */
  diagram?: Diagram
  /** The diagram behind the position on the board (linked or not), for its details. */
  shown?: Diagram
  onEdit?: () => void
  onToSolution?: () => void
  onToDiagram?: () => void
  onSelectGame: (index: number) => void
  onSelect: (id: string) => void
  onStep: (step: Step) => void
  /** While exploring, the arrow keys step through the reader's own moves: this hands the reader's key handler the stepper. */
  onExploreKeys: (stepper: ((step: Step) => boolean) | null) => void
  /** Focus: the book hidden and the board panel wide (key F). */
  focus?: boolean
  onFocus?: () => void
  /** Moves the board panel to the other side of the book. */
  onSwapSide?: () => void
  children?: ReactNode
}

export function BoardPanel(props: Props) {
  const { bookId, games, game, byId, node, diagram, shown, onSelectGame, onSelect, onStep, children } = props
  const { t, i18n } = useTranslation()
  const [orientation, setOrientation] = useState<'white' | 'black'>('white')
  const [figurines, setFigurines] = useState(() => load('figurines', false))
  const [copied, setCopied] = useState(false)

  // Whether the board changed by one move (animated) rather than jumping somewhere else.
  const shownId = diagram ? `d:${diagram.id}` : node?.id
  const [last, setLast] = useState({ id: shownId, step: false })
  if (last.id !== shownId) {
    const before = last.id ? byId.get(last.id) : undefined
    setLast({ id: shownId, step: !!node && !!before && !diagram && (node.parent === before.id || before.parent === node.id) })
  }
  const step = last.step

  const toggleFigurines = (on: boolean) => {
    setFigurines(on)
    save('figurines', on)
  }
  const bookFen = diagram
    ? diagram.placement
      ? `${diagram.placement} ${diagram.turn ?? 'w'} - - 0 1`
      : null
    : (node?.fen ?? START_FEN)

  // Exploring: the reader's own moves from the book's position, until the book moves on.
  const [explore, setExplore] = useState<Exploring | null>(null)
  if (explore && explore.base !== bookFen) setExplore(null)
  const fen = explore?.at ? explore.moves[explore.at - 1].fen : bookFen
  const free = !!fen && !!explore && !isPlayable(explore.base)
  const onMove = (from: string, to: string | null) => {
    if (!explore || !fen) return false
    const move = exploreMove(fen, from, to)
    if (!move) return false
    setExplore({ ...explore, moves: [...explore.moves.slice(0, explore.at), move], at: explore.at + 1 })
    return true
  }
  const exploreStep = (to: Step) => {
    if (!explore) return false
    const at = { start: 0, prev: Math.max(0, explore.at - 1), next: Math.min(explore.moves.length, explore.at + 1), end: explore.moves.length }[to]
    setExplore({ ...explore, at })
    return true
  }
  const { onExploreKeys } = props
  useEffect(() => {
    onExploreKeys(explore ? exploreStep : null)
  })

  const [engineOn, toggleEngine] = useEngineSwitch()
  const lang = i18n.resolvedLanguage ?? 'en'
  const exploreNumbers = explore ? lineNumbers(explore.base, explore.moves.length) : []
  // The engine's line, clicked: played on the board after what is there (the moves after it are dropped).
  const playLine = (moves: ExploreMove[]) => {
    if (!bookFen) return
    const kept = explore ? explore.moves.slice(0, explore.at) : []
    const all = [...kept, ...moves]
    setExplore({ base: bookFen, moves: all, at: all.length })
  }

  // The reader's arrows and circles, kept per position.
  const annotations = useUserData<Annotations>(bookId, 'annotations', NO_ANNOTATIONS)
  const key = fen ? positionKey(fen) : null
  const notes = key ? annotations.data[key] : undefined
  const setNotes = (n: { arrows: [string, string, string][]; circles: string[] }) =>
    key &&
    annotations.update((old) => {
      const next = { ...old }
      if (n.arrows.length || n.circles.length) next[key] = n
      else delete next[key]
      return next
    })

  const copyFen = async () => {
    if (!fen) return
    await navigator.clipboard.writeText(fen)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <aside className="board-panel">
      {game ? (
        <label className="game-select">
          <span>{t('reader.game')}</span>
          <select value={games.indexOf(game)} onChange={(e) => onSelectGame(Number(e.target.value))}>
            {games.map((g, i) => (
              <option key={g.id} value={i}>
                {g.title ?? t('reader.untitled', { n: i + 1 })}
              </option>
            ))}
          </select>
        </label>
      ) : (
        <p className="hint">{t('reader.noGames')}</p>
      )}
      <BoardFrame>
        <Board
          id="reader-board"
          fen={fen ?? EMPTY_FEN}
          orientation={orientation}
          animate={step || !!explore}
          onMove={explore ? onMove : undefined}
          offBoard={free}
          notes={notes}
          onNotes={fen ? setNotes : undefined}
        />
      </BoardFrame>

      <div className="nav">
        <button type="button" onClick={() => onStep('start')} title={t('reader.start')} aria-label={t('reader.start')}>⏮</button>
        <button type="button" onClick={() => onStep('prev')} title={t('reader.prev')} aria-label={t('reader.prev')}>◀</button>
        <button type="button" onClick={() => onStep('next')} title={t('reader.next')} aria-label={t('reader.next')}>▶</button>
        <button type="button" onClick={() => onStep('end')} title={t('reader.end')} aria-label={t('reader.end')}>⏭</button>
        <button
          type="button"
          onClick={() => setOrientation((o) => (o === 'white' ? 'black' : 'white'))}
          title={t('reader.flip')}
          aria-label={t('reader.flip')}
        >
          ⇅
        </button>
        <button type="button" className={engineOn ? 'active' : ''} onClick={toggleEngine} aria-pressed={engineOn} title={t('engine.keyHint')}>
          {t('engine.toggle')}
        </button>
        {props.onSwapSide && !props.focus && (
          <button type="button" onClick={props.onSwapSide} title={t('board.swapSide')} aria-label={t('board.swapSide')}>⇄</button>
        )}
        {props.onFocus && (
          <button type="button" className={props.focus ? 'active' : ''} onClick={props.onFocus} title={t('board.focus')} aria-label={t('board.focus')} aria-pressed={!!props.focus}>
            ⛶
          </button>
        )}
      </div>

      {/* Everything below the navigation scrolls; the board itself always stays in view. */}
      <div className="panel-scroll">
        {engineOn && fen && (
          <div className="engine-pinned">
            <EngineLine fen={fen} lang={lang} figurines={figurines} onPlay={bookFen ? playLine : undefined} />
          </div>
        )}
        {/* Below the board, so that showing or hiding it never moves the board. */}
        <div className="board-info">
          {shown && <DiagramInfo {...props} diagram={shown} linked={!diagram} />}
          {!shown && props.onToDiagram && (
            <button type="button" className="link" onClick={props.onToDiagram}>{t('reader.toDiagram')}</button>
          )}
        </div>

        {explore && (
          <div className="explore">
            <span className="hint">{free ? t('explore.free') : t('explore.legal')}</span>
            {explore.moves.length > 0 && (
              <span className="explore-moves">
                {explore.moves.map((m, i) => (
                  <Fragment key={i}>
                    {!free && exploreNumbers[i] && <span className="move-number">{exploreNumbers[i]}</span>}
                    <button
                      type="button"
                      className={`move${i + 1 === explore.at ? ' selected' : ''}`}
                      onClick={() => setExplore({ ...explore, at: i + 1 })}
                    >
                      {free ? m.label : displaySan(m.label, lang, figurines)}
                    </button>
                  </Fragment>
                ))}
              </span>
            )}
            <button type="button" onClick={() => setExplore(null)}>{t('explore.back')}</button>
          </div>
        )}

        <div className="tools">
          <button
            type="button"
            className={explore ? 'active' : ''}
            onClick={() => setExplore(explore ? null : bookFen ? { base: bookFen, moves: [], at: 0 } : null)}
            disabled={!bookFen}
            title={t('explore.hint')}
          >
            {t('explore.button')}
          </button>
          {notes && (
            <button type="button" onClick={() => setNotes({ arrows: [], circles: [] })} title={t('notes.hint')}>
              {t('notes.clear')}
            </button>
          )}
          <button type="button" onClick={copyFen} disabled={!fen}>{copied ? t('reader.copied') : t('reader.copyFen')}</button>
          {game && (
            <a className="button" href={api.pgnUrl(bookId, game.id)} download={`${game.id}.pgn`}>
              {t('reader.exportPgn')}
            </a>
          )}
          <label className="check">
            <input type="checkbox" checked={figurines} onChange={(e) => toggleFigurines(e.target.checked)} />
            {t('reader.figurines')}
          </label>
        </div>

        {game && node && (
          <MoveTree
            byId={byId}
            root={byId.get(game.root)!}
            selected={diagram ? '' : node.id}
            onSelect={onSelect}
            lang={i18n.resolvedLanguage ?? 'en'}
            figurines={figurines}
          />
        )}
        <p className="hint">{t('reader.keys')}</p>
        {children}
      </div>
    </aside>
  )
}

function DiagramInfo({ diagram, linked, onEdit, onToSolution, onToDiagram }: Props & { diagram: Diagram; linked: boolean }) {
  const { t } = useTranslation()
  const certainty = diagram.confidence ?? 1
  const uncertain = diagram.uncertain ?? []
  return (
    <div className="diagram-info">
      <strong>{diagram.label ? t('reader.diagramNumbered', { label: diagram.label }) : t('reader.diagram')}</strong>
      {!diagram.placement && <span className="hint">{t('reader.diagramUnread')}</span>}
      {diagram.placement && diagram.corrected && <span className="hint">{t('reader.corrected')}</span>}
      {diagram.placement && !diagram.corrected && !diagram.fixed && certainty < 1 && (
        <span className={`hint${uncertain.length ? ' warn' : ''}`}>
          {t('reader.certainty', { pct: Math.round(certainty * 100) })}
          {uncertain.length > 0 && ` · ${t('reader.toCheck', { count: uncertain.length })}`}
        </span>
      )}
      {!diagram.corrected &&
        diagram.check?.filter((c) => c !== 'doubtful' && c !== 'unread').map((c) => (
          <span key={c} className={`hint${c === 'fixed' ? '' : ' warn'}`}>{t(`reader.check.${c}`)}</span>
        ))}
      {diagram.placement && !linked && <span className="hint">{t('reader.diagramUnlinked')}</span>}
      <span className="actions">
        {onToSolution && <button type="button" onClick={onToSolution}>{t('reader.toSolution')}</button>}
        {onEdit && <button type="button" onClick={onEdit}>{t('reader.editDiagram')}</button>}
      </span>
      {onToDiagram && !onToSolution && (
        <button type="button" className="link" onClick={onToDiagram}>{t('reader.toDiagram')}</button>
      )}
    </div>
  )
}
