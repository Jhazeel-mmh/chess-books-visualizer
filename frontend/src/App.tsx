import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Route, Routes } from 'react-router-dom'
import { LANGUAGES } from './i18n'
import { Library } from './pages/Library'
import { Reader } from './pages/Reader'

// The trainer (and its chess logic) loads only when it is used.
const Trainer = lazy(() => import('./pages/Trainer').then((m) => ({ default: m.Trainer })))

export default function App() {
  const { t, i18n } = useTranslation()
  return (
    <BrowserRouter>
      <header className="app-header">
        <Link to="/" className="brand">♞ {t('app.title')}</Link>
        <Link to="/train" className="header-link">{t('train.title')}</Link>
        <label className="lang">
          <span className="sr-only">{t('app.language')}</span>
          <select value={i18n.resolvedLanguage} onChange={(e) => i18n.changeLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>{l === 'es' ? 'Español' : 'English'}</option>
            ))}
          </select>
        </label>
      </header>
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/books/:id" element={<Reader />} />
        <Route
          path="/train"
          element={
            <Suspense fallback={<p className="notice">…</p>}>
              <Trainer />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
