import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { api, type BookMeta } from '../api'

const ACCEPT = '.epub,.pdf'

export function Library() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const books = useQuery({
    queryKey: ['books'],
    queryFn: api.books,
    // Keep polling while a book is still being analyzed.
    refetchInterval: (q) => (q.state.data?.some((b) => b.status === 'queued' || b.status === 'analyzing') ? 1000 : false),
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['books'] })
  const upload = useMutation({ mutationFn: api.upload, onSuccess: refresh })

  return (
    <main className="library">
      <section className="import">
        <label className="button primary">
          {upload.isPending ? t('library.uploading') : t('library.import')}
          <input
            type="file"
            accept={ACCEPT}
            hidden
            disabled={upload.isPending}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) upload.mutate(file)
              e.target.value = ''
            }}
          />
        </label>
        <span className="hint">{t('library.importHint')}</span>
        <Link to="/train" className="button primary train-today">{t('train.today')}</Link>
      </section>

      <h2>{t('library.title')}</h2>
      {books.data?.length === 0 && <p className="notice">{t('library.empty')}</p>}
      <ul className="books">
        {books.data?.map((b) => <BookRow key={b.id} book={b} onChange={refresh} />)}
      </ul>
    </main>
  )
}

function BookRow({ book, onChange }: { book: BookMeta; onChange: () => void }) {
  const { t } = useTranslation()
  const remove = useMutation({ mutationFn: () => api.remove(book.id), onSuccess: onChange })
  const reanalyze = useMutation({ mutationFn: () => api.reanalyze(book.id), onSuccess: onChange })
  const s = book.stats

  return (
    <li className="book">
      <div className="book-main">
        <span className="format">{book.format}</span>
        <strong>{book.title}</strong>
        <span className={`status ${book.status}`}>
          {t(`library.status.${book.status}`)}
          {book.status === 'analyzing' && book.progress != null && ` ${Math.round(book.progress * 100)}%`}
        </span>
      </div>
      <div className="book-detail">
        {s && t('library.stats', { games: s.games, resolved: s.moves_resolved, found: s.moves_found })}
        {s?.diagrams ? <span>{t('library.diagrams', { read: s.diagrams_read, total: s.diagrams })}</span> : null}
        {s?.diagrams_to_check ? <span className="hint">{t('library.toCheck', { count: s.diagrams_to_check })}</span> : null}
        {book.error && <code className="error">{book.error}</code>}
      </div>
      <div className="book-actions">
        {book.status === 'ready' && <Link className="button primary" to={`/books/${book.id}`}>{t('library.open')}</Link>}
        <button type="button" onClick={() => reanalyze.mutate()} disabled={book.status === 'analyzing'}>
          {t('library.reanalyze')}
        </button>
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
