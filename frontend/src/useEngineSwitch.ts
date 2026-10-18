import { useCallback, useEffect, useState } from 'react'
import { load, save } from './storage'

/**
 * Whether the engine's evaluation is shown, remembered between visits, and toggled with the "E"
 * key (not while typing). Shared by reading and by the review after a problem.
 */
export function useEngineSwitch(keys = true): [boolean, () => void] {
  const [on, setOn] = useState(() => load('engine', false))
  const toggle = useCallback(() => {
    setOn((was) => {
      save('engine', !was)
      return !was
    })
  }, [])
  useEffect(() => {
    if (!keys) return
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (el.closest?.('input, select, textarea') || e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key === 'e' || e.key === 'E') {
        e.preventDefault()
        toggle()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [keys, toggle])
  return [on, toggle]
}
