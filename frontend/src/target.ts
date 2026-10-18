import type { MarkKind } from './api'

/** What the book view highlights and keeps in view: a move, an unresolved fragment or a diagram. */
export interface Target {
  kind: MarkKind
  id: string
  /** Blocks where it is printed (a move may be mentioned several times). */
  blocks: number[]
  /** True when the user clicked it in the book: it is already in view, so don't scroll. */
  fromBook?: boolean
}

export const MARK_ATTR: Record<MarkKind, string> = {
  move: 'data-cbv-node',
  unresolved: 'data-cbv-unresolved',
  diagram: 'data-cbv-diagram',
}
