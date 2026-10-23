import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { api, SIGNED_OUT } from './api'
import { Footer } from './components/Footer'
import { LANGUAGES } from './i18n'
import { Library } from './pages/Library'
import { Reader } from './pages/Reader'
import { signedOut } from './session'

// The trainer (and its chess logic) loads only when it is used; so do the licenses and the legal
// texts, the account pages and the copyright forms.
const Trainer = lazy(() => import('./pages/Trainer').then((m) => ({ default: m.Trainer })))
const legalPages = () => import('./pages/Legal')
const Licenses = lazy(() => legalPages().then((m) => ({ default: m.Licenses })))
const Policy = lazy(() => legalPages().then((m) => ({ default: m.Policy })))
const Plans = lazy(() => import('./pages/Plans').then((m) => ({ default: m.Plans })))
const accountPages = () => import('./pages/Account')
const SignIn = lazy(() => accountPages().then((m) => ({ default: m.SignIn })))
const SignUp = lazy(() => accountPages().then((m) => ({ default: m.SignUp })))
const Verify = lazy(() => accountPages().then((m) => ({ default: m.Verify })))
const Forgot = lazy(() => accountPages().then((m) => ({ default: m.Forgot })))
const Reset = lazy(() => accountPages().then((m) => ({ default: m.Reset })))
const Account = lazy(() => accountPages().then((m) => ({ default: m.Account })))
const copyrightPages = () => import('./pages/Copyright')
const CopyrightNotice = lazy(() => copyrightPages().then((m) => ({ default: m.CopyrightNotice })))
const CounterNotice = lazy(() => copyrightPages().then((m) => ({ default: m.CounterNotice })))

const later = (page: ReactNode) => <Suspense fallback={<p className="notice">…</p>}>{page}</Suspense>

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}

/** The local app opens straight on the library; a hosted one first asks who you are. */
export function Shell() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  useEffect(() => {
    const ended = () => signedOut(queryClient)
    window.addEventListener(SIGNED_OUT, ended)
    return () => window.removeEventListener(SIGNED_OUT, ended)
  }, [queryClient])
  const hosted = me.data?.hosted ?? false
  const signedIn = !hosted || me.data?.user != null
  // A hosted site's plans, terms, privacy notice and copyright policy: for anyone, signed in or not.
  const policies = [
    <Route key="plans" path="/plans" element={later(<Plans />)} />,
    <Route key="terms" path="/terms" element={later(<Policy name="terms" />)} />,
    <Route key="privacy" path="/privacy" element={later(<Policy name="privacy" />)} />,
    <Route key="copyright" path="/copyright/policy" element={later(<Policy name="copyright" />)} />,
  ]

  return (
    <>
      <header className="app-header">
        <Link to="/" className="brand">♞ {t('app.title')}</Link>
        {signedIn && <Link to="/train" className="header-link">{t('train.title')}</Link>}
        {hosted && signedIn && <Link to="/account" className="header-account">{t('account.title')}</Link>}
        <label className="lang">
          <span className="sr-only">{t('app.language')}</span>
          <select value={i18n.resolvedLanguage} onChange={(e) => i18n.changeLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l} value={l}>{l === 'es' ? 'Español' : 'English'}</option>
            ))}
          </select>
        </label>
      </header>
      {me.isPending ? (
        <p className="notice">…</p>
      ) : signedIn ? (
        <Routes>
          <Route path="/" element={<Library />} />
          <Route path="/books/:id" element={<Reader />} />
          <Route path="/train" element={later(<Trainer />)} />
          <Route path="/licenses" element={later(<Licenses />)} />
          {hosted && <Route path="/account" element={later(<Account />)} />}
          {hosted && <Route path="/reset" element={later(<Reset />)} />}
          {hosted && <Route path="/verify" element={<Navigate to="/" replace />} />}
          {hosted && <Route path="/copyright" element={later(<CopyrightNotice />)} />}
          {hosted && <Route path="/copyright/counter/:id" element={later(<CounterNotice />)} />}
          {hosted && policies}
        </Routes>
      ) : (
        <Routes>
          <Route path="/signup" element={later(<SignUp />)} />
          <Route path="/verify" element={later(<Verify />)} />
          <Route path="/forgot" element={later(<Forgot />)} />
          <Route path="/reset" element={later(<Reset />)} />
          <Route path="/licenses" element={later(<Licenses />)} />
          <Route path="/copyright" element={later(<CopyrightNotice />)} />
          {policies}
          {/* Any other address: sign in first, then the page asked for appears. */}
          <Route path="*" element={later(<SignIn />)} />
        </Routes>
      )}
      <Footer />
    </>
  )
}
