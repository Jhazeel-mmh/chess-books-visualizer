/**
 * Scrolls `container` so that `el` is in view, moving nothing else.
 *
 * `Element.scrollIntoView` also scrolls every scrollable ancestor (the page, and the
 * parent page of an iframe), which makes the board panel jump while stepping through moves.
 */
export function scrollWithin(container: HTMLElement, el: Element, block: 'start' | 'center' = 'center') {
  const box = container.getBoundingClientRect()
  const r = el.getBoundingClientRect()
  const top = r.top - box.top + container.scrollTop
  const left = r.left - box.left + container.scrollLeft
  container.scrollTo({
    top: Math.max(0, block === 'start' ? top - 8 : top - (container.clientHeight - r.height) / 2),
    left: container.scrollWidth > container.clientWidth ? Math.max(0, left - (container.clientWidth - r.width) / 2) : undefined,
  })
}

/** True if `el` is entirely inside the visible part of `container`. */
export function visibleWithin(container: HTMLElement, el: Element): boolean {
  const box = container.getBoundingClientRect()
  const r = el.getBoundingClientRect()
  return r.top >= box.top && r.bottom <= box.bottom
}
