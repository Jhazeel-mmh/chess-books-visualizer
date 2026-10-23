import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { blocks } from '../markdown'

// The legal texts' Markdown (see markdown.ts), built as elements, never as HTML, so nothing in a
// text can run.

const INLINE = /\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\{(\w+)\}/g

function inline(text: string, values: Record<string, ReactNode>): ReactNode[] {
  const out: ReactNode[] = []
  let at = 0
  for (const m of text.matchAll(INLINE)) {
    if (m.index > at) out.push(text.slice(at, m.index))
    const [whole, bold, code, label, href, blank] = m
    const key = out.length
    if (bold !== undefined) out.push(<strong key={key}>{inline(bold, values)}</strong>)
    else if (code !== undefined) out.push(<code key={key}>{code}</code>)
    else if (label !== undefined) out.push(link(label, href, values, key))
    else out.push(blank in values ? <Fragment key={key}>{values[blank]}</Fragment> : whole)
    at = m.index + whole.length
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}

function link(label: string, href: string, values: Record<string, ReactNode>, key: number): ReactNode {
  const children = inline(label, values)
  if (href.startsWith('/')) return <Link key={key} to={href}>{children}</Link>
  if (/^(https:|mailto:)/.test(href)) return <a key={key} href={href}>{children}</a>
  return <Fragment key={key}>{children}</Fragment> // anything else (javascript:…) is only its words
}

export function Markdown({ text, values = {} }: { text: string; values?: Record<string, ReactNode> }) {
  return (
    <>
      {blocks(text).map((b, i) => {
        if ('items' in b) {
          const List = b.kind
          return <List key={i}>{b.items.map((item, j) => <li key={j}>{inline(item, values)}</li>)}</List>
        }
        const Tag = b.kind
        return <Tag key={i}>{inline(b.text, values)}</Tag>
      })}
    </>
  )
}
