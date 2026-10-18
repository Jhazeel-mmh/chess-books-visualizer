import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { MoveFix, MoveNode } from '../api'
import { legalMove } from '../explore'
import { typedMove } from '../fixMoves'
import type { FixBox } from './PdfView'
import { Board } from './Board'
import { BoardFrame } from './BoardFrame'

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'

interface Props {
  /** The place picked on the page, if any. */
  box: FixBox | null
  /** The game node the fix most likely follows (its position is the one before the move). */
  base: MoveNode | null
  byId: Map<string, MoveNode>
  fixes: MoveFix[]
  saving: boolean
  onSave: (fixes: MoveFix[]) => void
  onGoTo: (page: number) => void
  onCancel: () => void
  onClose: () => void
}

/** Entering a move the app could not read on a page, or removing a false one; and the list of fixes. */
export function MoveFixer({ box, base, byId, fixes, saving, onSave, onGoTo, onCancel, onClose }: Props) {
  const { t } = useTranslation()
  return (
    <aside className="board-panel move-fixer">
      <div className="fixer-head">
        <strong>{t('fix.title')}</strong>
        <button type="button" onClick={onClose}>{t('fix.done')}</button>
      </div>
      {box ? (
        <FixEditor
          key={`${box.page}:${box.rect.join(',')}:${base?.id ?? ''}`}
          box={box}
          base={base}
          byId={byId}
          saving={saving}
          onSave={(fix) => onSave([...fixes.filter((f) => !sameBox(f, box)), fix])}
          onCancel={onCancel}
        />
      ) : (
        <p className="hint">{t('fix.howTo')}</p>
      )}
      <div className="panel-scroll">
        <h4>{t('fix.list', { count: fixes.length })}</h4>
        {fixes.length === 0 && <p className="hint">{t('fix.none')}</p>}
        <ul className="fix-list">
          {fixes.map((f, i) => (
            <li key={i}>
              <button type="button" className="link" onClick={() => onGoTo(f.page)}>
                {t('fix.onPage', { page: f.page + 1 })}
              </button>
              <span>{f.remove ? t('fix.removed') : f.san ?? f.uci}</span>
              <button type="button" disabled={saving} onClick={() => onSave(fixes.filter((_, j) => j !== i))} title={t('fix.delete')} aria-label={t('fix.delete')}>✕</button>
            </li>
          ))}
        </ul>
      </div>
    </aside>
  )
}

/** "12.Nf3" or "12...Nc6", from the position after the move. */
function numbered(fenAfter: string, san: string): string {
  const [, side, , , , full = '1'] = fenAfter.split(' ')
  return side === 'b' ? `${full}.${san}` : `${Number(full) - 1}...${san}`
}

const sameBox = (f: MoveFix, box: FixBox) => f.page === box.page && f.rect.every((v, i) => Math.abs(v - box.rect[i]) < 0.5)

interface EditorProps {
  box: FixBox
  base: MoveNode | null
  byId: Map<string, MoveNode>
  saving: boolean
  onSave: (fix: MoveFix) => void
  onCancel: () => void
}

/**
 * The position before the move (the game's, stepped back or forward along it, or reached by playing
 * moves on the board), and the move itself: the last one played or typed.
 */
function FixEditor({ box, base, byId, saving, onSave, onCancel }: EditorProps) {
  const { t } = useTranslation()
  const [nodeId, setNodeId] = useState(base?.id ?? null)
  const node = nodeId ? byId.get(nodeId) : undefined
  const startFen = node?.fen ?? START_FEN
  // Moves played on the board from the game's position: the last is the fix, the others lead to its position.
  const [played, setPlayed] = useState<{ san: string; uci: string; fen: string }[]>([])
  const [typed, setTyped] = useState('')
  const [badTyped, setBadTyped] = useState(false)
  const fen = played.length ? played[played.length - 1].fen : startFen
  const last = played[played.length - 1]
  const before = played.length > 1 ? played[played.length - 2].fen : startFen
  const label = node?.san ? numbered(node.fen, node.san) : t('fix.startPosition')

  const stepGame = (to: 'back' | 'forward') => {
    const next = to === 'back' ? node?.parent : node?.children[0]
    if (next) {
      setNodeId(next)
      setPlayed([])
    }
  }
  const playMove = (from: string, to: string | null) => {
    const m = to ? legalMove(fen, from, to) : null
    if (!m) return false
    const uci = from + to + (m.label.includes('=') ? m.label.split('=')[1][0].toLowerCase() : '')
    setPlayed([...played, { san: m.label, uci, fen: m.fen }])
    return true
  }
  const enterTyped = () => {
    const m = typedMove(fen, typed)
    setBadTyped(!m)
    if (m) {
      setPlayed([...played, m])
      setTyped('')
    }
  }
  const rect = box.rect.map((v) => Math.round(v * 10) / 10) as MoveFix['rect']

  return (
    <div className="fix-editor">
      <p className="hint">{t('fix.onPage', { page: box.page + 1 })}</p>
      <div className="fix-base">
        <span>{t('fix.after', { move: label })}</span>
        <button type="button" onClick={() => stepGame('back')} disabled={!node?.parent} title={t('fix.earlier')} aria-label={t('fix.earlier')}>◀</button>
        <button type="button" onClick={() => stepGame('forward')} disabled={!node?.children.length} title={t('fix.later')} aria-label={t('fix.later')}>▶</button>
      </div>
      <BoardFrame>
        <Board id="fix-board" fen={fen} orientation={fen.split(' ')[1] === 'b' ? 'black' : 'white'} animate onMove={playMove} />
      </BoardFrame>
      <div className="fix-move">
        <input
          value={typed}
          placeholder={t('fix.typeMove')}
          aria-label={t('fix.typeMove')}
          className={badTyped ? 'invalid' : ''}
          onChange={(e) => {
            setTyped(e.target.value)
            setBadTyped(false)
          }}
          onKeyDown={(e) => e.key === 'Enter' && enterTyped()}
        />
        <button type="button" onClick={enterTyped} disabled={!typed.trim()}>{t('fix.enter')}</button>
        <button type="button" onClick={() => setPlayed(played.slice(0, -1))} disabled={!played.length}>{t('fix.undo')}</button>
      </div>
      <p>
        {last ? (
          <>
            {t('fix.theMove')} <strong>{last.san}</strong>
            {played.length > 1 && <span className="hint"> ({t('fix.reachedBy', { moves: played.slice(0, -1).map((m) => m.san).join(' ') })})</span>}
          </>
        ) : (
          <span className="hint">{t('fix.playIt')}</span>
        )}
      </p>
      <div className="actions">
        <button type="button" className="primary" disabled={!last || saving} onClick={() => last && onSave({ page: box.page, rect, before, uci: last.uci, san: last.san })}>
          {t('fix.save')}
        </button>
        {box.mark && (
          <button type="button" disabled={saving} onClick={() => onSave({ page: box.page, rect, remove: true })}>{t('fix.notAMove')}</button>
        )}
        <button type="button" onClick={onCancel}>{t('fix.cancel')}</button>
      </div>
      {saving && <p className="hint">{t('fix.saving')}</p>}
    </div>
  )
}
