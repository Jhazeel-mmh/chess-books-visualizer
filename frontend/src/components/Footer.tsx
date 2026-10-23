import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api'
import { sourceUrl } from '../legal'

export function Footer() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const hosted = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity }).data?.hosted
  // The reader fills the screen, so its pages have no footer.
  if (pathname.startsWith('/books/')) return null
  const source = sourceUrl()
  return (
    <footer className="app-footer">
      {hosted && <Link to="/plans">{t('plans.link')}</Link>}
      {hosted && <Link to="/terms">{t('legal.terms')}</Link>}
      {hosted && <Link to="/privacy">{t('legal.privacy')}</Link>}
      {hosted && <Link to="/copyright/policy">{t('copyright.link')}</Link>}
      <Link to="/licenses">{t('legal.licenses.link')}</Link>
      {source && <a href={source}>{t('legal.sourceCode')}</a>}
    </footer>
  )
}
