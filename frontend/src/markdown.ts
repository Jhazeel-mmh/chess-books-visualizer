// The little Markdown the legal pages are written in (src/policies): headings, paragraphs, lists,
// **bold**, `code`, [links](/somewhere) and {blanks} the page fills in (components/Markdown.tsx).

export type Block =
  | { kind: 'h1' | 'h2' | 'h3' | 'p'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }

export function blocks(text: string): Block[] {
  const out: Block[] = []
  let para: string[] = []
  let list: { kind: 'ul' | 'ol'; items: string[] } | null = null
  const flush = () => {
    if (para.length) out.push({ kind: 'p', text: para.join(' ') })
    if (list) out.push(list)
    para = []
    list = null
  }
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    const heading = /^(#{1,3}) (.+)$/.exec(line)
    const item = /^(-|\d+\.) (.+)$/.exec(line)
    if (!line) {
      flush()
    } else if (heading) {
      flush()
      out.push({ kind: `h${heading[1].length}` as 'h1' | 'h2' | 'h3', text: heading[2] })
    } else if (item) {
      const kind = item[1] === '-' ? 'ul' : 'ol'
      if (para.length || (list && list.kind !== kind)) flush()
      list ??= { kind, items: [] }
      list.items.push(item[2])
    } else if (list && /^\s/.test(raw)) {
      list.items[list.items.length - 1] += ` ${line}` // an item that goes on over several lines
    } else {
      if (list) flush()
      para.push(line)
    }
  }
  flush()
  return out
}

/** The blanks a text has: {name}. */
export function blanks(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1])
}
