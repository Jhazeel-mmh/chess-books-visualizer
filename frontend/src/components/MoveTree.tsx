import { Fragment, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import type { MoveNode } from '../api'
import { displaySan, moveNumber, nagSymbols } from '../notation'
import { scrollWithin, visibleWithin } from '../scroll'

interface Props {
  byId: Map<string, MoveNode>
  root: MoveNode
  selected: string
  onSelect: (id: string) => void
  lang: string
  figurines: boolean
}

/** The game as PGN-style text: main line with nested variations in brackets. */
export function MoveTree(props: Props) {
  const box = useRef<HTMLDivElement>(null)
  // Keep the selected move visible inside the list (and only the list: the page must not move).
  useEffect(() => {
    const el = box.current?.querySelector('.move.selected')
    if (box.current && el && !visibleWithin(box.current, el)) scrollWithin(box.current, el)
  }, [props.selected])
  const first = props.root.children[0]
  if (!first) return null
  return (
    <div className="move-tree" ref={box}>
      <Line {...props} start={props.byId.get(first)!} depth={0} />
    </div>
  )
}

function Line(props: Props & { start: MoveNode; depth: number }) {
  const { byId, start, depth } = props
  const items = []
  let node: MoveNode | undefined = start
  let showNumber = true
  while (node) {
    const parent = byId.get(node.parent!)!
    items.push(<Move key={node.id} {...props} node={node} parent={parent} showNumber={showNumber} />)
    showNumber = false
    if (parent.children[0] === node.id && parent.children.length > 1) {
      for (const alt of parent.children.slice(1)) {
        items.push(
          <Fragment key={`v${alt}`}>
            {' '}
            <span className={`variation depth-${Math.min(depth + 1, 3)}`}>
              ( <Line {...props} start={byId.get(alt)!} depth={depth + 1} /> )
            </span>{' '}
          </Fragment>,
        )
      }
      showNumber = true
    }
    node = node.children.length ? byId.get(node.children[0]) : undefined
  }
  return <>{items}</>
}

function Move(props: Props & { node: MoveNode; parent: MoveNode; showNumber: boolean }) {
  const { node, parent, showNumber, selected, onSelect, lang, figurines } = props
  const { t } = useTranslation()
  const uncertainTitle = t('reader.uncertainMove')
  const { number, white } = moveNumber(parent.fen)
  const label = white ? `${number}.` : showNumber ? `${number}…` : ''
  return (
    <>
      {label && <span className="move-number">{label}</span>}
      <button
        type="button"
        className={`move${node.id === selected ? ' selected' : ''}${node.mainline ? ' main' : ''}${node.uncertain ? ' uncertain' : ''}`}
        onClick={() => onSelect(node.id)}
        title={node.uncertain ? uncertainTitle : undefined}
      >
        {displaySan(node.san!, lang, figurines)}
        {nagSymbols(node.nags)}
      </button>{' '}
    </>
  )
}
