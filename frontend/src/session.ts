import type { QueryClient } from '@tanstack/react-query'
import type { Me } from './api'
import { forgetPersonal } from './storage'

/** After signing out of a hosted app (or the session ending): nothing of that reader stays. */
export function signedOut(queryClient: QueryClient) {
  forgetPersonal()
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== 'me' })
  queryClient.setQueryData<Me>(['me'], { hosted: true, user: null })
}
