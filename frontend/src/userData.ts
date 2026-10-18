import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type UserData } from './api'

const SAVE_AFTER_MS = 600

/**
 * Something the reader keeps for a book (solving progress, arrows and circles), saved with the book.
 *
 * Loaded once; every change is shown at once and saved shortly after (and when leaving the page).
 */
export function useUserData<T extends object>(bookId: string, name: UserData, empty: T) {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['user', bookId, name], queryFn: () => api.userData<T>(bookId, name), staleTime: Infinity })
  const [edited, setEdited] = useState<T | null>(null)
  const data = edited ?? query.data ?? empty

  // Save a while after the last change, and right away if the page goes before that.
  const pending = useRef<T | null>(null)
  useEffect(() => {
    if (!edited) return
    pending.current = edited
    queryClient.setQueryData(['user', bookId, name], edited)
    const timer = setTimeout(() => {
      pending.current = null
      void api.saveUserData(bookId, name, edited)
    }, SAVE_AFTER_MS)
    return () => clearTimeout(timer)
  }, [edited, bookId, name, queryClient])
  useEffect(
    () => () => {
      if (pending.current) void api.saveUserData(bookId, name, pending.current)
    },
    [bookId, name],
  )

  const loadedData = query.data
  const update = useCallback(
    (change: (old: T) => T) => setEdited((old) => change(old ?? loadedData ?? empty)),
    [loadedData, empty],
  )
  return { data, update, loaded: query.isSuccess }
}

/** The reader's arrows and circles on one position. */
export interface PositionNotes {
  /** [from, to, colour] */
  arrows: [string, string, string][]
  circles: string[]
}

/** Arrows and circles of a book, by position (see ``positionKey``). */
export type Annotations = Record<string, PositionNotes>

/** The same position always has the same key: its pieces and the side to move. */
export function positionKey(fen: string): string {
  return fen.split(' ').slice(0, 2).join(' ')
}
