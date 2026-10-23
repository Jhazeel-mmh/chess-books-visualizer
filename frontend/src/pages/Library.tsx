import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, ApiError, type BookMeta, type Usage } from '../api'
import { AdSlot } from '../components/AdSlot'
import { usePlan } from '../plan'

const ACCEPT = '.epub,.pdf'
const MB = 2 ** 20
const REFUSED = new Set(['too_big', 'unpacked', 'format', 'books', 'storage', 'too_many'])

export function Library() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const books = useQuery({
    queryKey: ['books'],
    queryFn: api.books,
    // Keep polling while a book is still being analyzed.
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === 'queued' || b.status === 'analyzing') ? 1000 : false),
  })
  const hosted = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity }).data?.hosted
  const usage = useQuery({ queryKey: ['usage'], queryFn: api.usage, enabled: hosted === true }).data
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['books'] })
    queryClient.invalidateQueries({ queryKey: ['usage'] })
  }
  // On the site, whoever uploads a book first says it is theirs to use.
  const [declared, setDeclared] = useState(false)
  const upload = useMutation({
    // A file over the size limit isn't sent at all: the server would stop it anyway.
    mutationFn: (file: File) => usage?.max_upload && file.size > usage.max_upload
      ? Promise.reject(new ApiError(413, 'Payload Too Large', 'too_big'))
      : api.upload(file, hosted && declared),
    onSuccess: refresh,
  })
  const undeclared = (hosted ?? false) && !declared
  const plan = usePlan()
  const full = upload.error instanceof ApiError && (upload.error.detail === 'books' || upload.error.detail === 'storage')

  return (
    <main className="library">
      <section className="import">
        <label className={`button primary${undeclared ? ' disabled' : ''}`}>
          {upload.isPending ? t('library.uploading') : t('library.import')}
          <input
            type="file"
            accept={ACCEPT}
            hidden
            disabled={upload.isPending || undeclared}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) upload.mutate(file)
              e.target.value = ''
            }}
          />
        </label>
        <span className="hint">
          {t(hosted ? 'library.importHintHosted' : 'library.importHint')}
          {usage?.max_books ? <span className="usage">{usageText(t, usage)}</span> : null}
        </span>
        <Link to="/train" className="button primary train-today">{t('train.today')}</Link>
        {hosted && (
          <label className="declare">
            <input type="checkbox" checked={declared} onChange={(e) => setDeclared(e.target.checked)} />
            {t('library.declare')}
          </label>
        )}
        {upload.isError && <p className="auth-problem" role="alert">{refusal(t, upload.error, usage)}</p>}
        {full && plan?.checkout && <p className="hint"><Link to="/plans">{t('plans.roomInPlus')}</Link></p>}
      </section>

      <h2>{t('library.title')}</h2>
      {books.data?.length === 0 && <p className="notice">{t('library.empty')}</p>}
      <ul className="books">
        {books.data?.map((b) => <BookRow key={b.id} book={b} onChange={refresh} />)}
      </ul>
      <AdSlot />
    </main>
  )
}

function BookRow({ book, onChange }: { book: BookMeta; onChange: () => void }) {
  const { t, i18n } = useTranslation()
  const remove = useMutation({ mutationFn: () => api.remove(book.id), onSuccess: onChange })
  const reanalyze = useMutation({ mutationFn: () => api.reanalyze(book.id), onSuccess: onChange })
  const s = book.stats

  return (
    <li className="book">
      <div className="book-main">
        <span className="format">{book.format}</span>
        <strong>{book.title}</strong>
        {book.disabled ? (
          <span className="status error">{t('library.status.disabled')}</span>
        ) : (
          <span className={`status ${book.status}`}>
            {t(`library.status.${book.status}`)}
            {book.status === 'analyzing' && book.progress != null && ` ${Math.round(book.progress * 100)}%`}
          </span>
        )}
      </div>
      {book.disabled && (
        <div className="book-detail disabled-detail">
          <span>{t('library.disabledText', { date: day(book.disabled.at, i18n.resolvedLanguage), claimant: book.disabled.claimant })}</span>
          {book.disabled.counter_at && (
            <span className="hint">{t('library.counterSent', { date: day(book.disabled.counter_at, i18n.resolvedLanguage) })}</span>
          )}
        </div>
      )}
      <div className="book-detail">
        {s && t('library.stats', { games: s.games, resolved: s.moves_resolved, found: s.moves_found })}
        {s?.diagrams ? <span>{t('library.diagrams', { read: s.diagrams_read, total: s.diagrams })}</span> : null}
        {s?.diagrams_to_check ? <span className="hint">{t('library.toCheck', { count: s.diagrams_to_check })}</span> : null}
        {book.error?.startsWith('limit: ') ? (
          <span className="error">{t(`library.limit.${book.error.slice(7)}`)}</span>
        ) : (
          book.error && <code className="error">{book.error}</code>
        )}
      </div>
      <div className="book-actions">
        {book.status === 'ready' && !book.disabled && <Link className="button primary" to={`/books/${book.id}`}>{t('library.open')}</Link>}
        {book.disabled && !book.disabled.counter_at && (
          <Link className="button" to={`/copyright/counter/${book.id}`}>{t('library.counterNotice')}</Link>
        )}
        {!book.disabled && (
          <button type="button" onClick={() => reanalyze.mutate()} disabled={book.status === 'analyzing'}>
            {t('library.reanalyze')}
          </button>
        )}
        <button
          type="button"
          onClick={() => window.confirm(t('library.confirmDelete', { title: book.title })) && remove.mutate()}
        >
          {t('library.delete')}
        </button>
      </div>
    </li>
  )
}

const day = (iso: string, lang?: string) => new Date(iso).toLocaleDateString(lang)

type T = ReturnType<typeof useTranslation>['t']

function usageText(t: T, u: Usage) {
  return t('library.usage', {
    books: u.books, maxBooks: u.max_books, mb: Math.ceil(u.bytes / MB), maxMb: u.max_bytes / MB, uploadMb: u.max_upload / MB,
  })
}

/** Why an upload wasn't taken, in words. */
function refusal(t: T, err: Error, usage?: Usage) {
  const why = err instanceof ApiError ? err.detail : null
  if (why === 'blocked') return t('library.blocked')
  if (!why || !REFUSED.has(why)) return t('library.uploadFailed')
  return t(`library.refused.${why}`, {
    mb: Math.round((why === 'storage' ? usage?.max_bytes ?? 0 : usage?.max_upload ?? 0) / MB), count: usage?.max_books,
  })
}
