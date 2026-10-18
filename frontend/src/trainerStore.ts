import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type TrainerRecord } from './api'

/** Where a reading block started, kept while the reader is in the book. */
export const READING_KEY = 'train.reading'
export interface ReadingStart {
  book: string
  from: number
  started: number
}

/** The trainer's record, and a way to change it (saved at once). */
export function useTrainer() {
  const queryClient = useQueryClient()
  const record = useQuery({ queryKey: ['trainer'], queryFn: api.trainer })
  const saving = useMutation({
    mutationFn: api.saveTrainer,
    onMutate: (next: TrainerRecord) => queryClient.setQueryData(['trainer'], next),
  })
  return { record: record.data, error: record.error, update: (next: TrainerRecord) => saving.mutate(next) }
}
