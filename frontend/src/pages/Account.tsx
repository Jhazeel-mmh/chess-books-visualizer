import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { leaveFor, usePlan } from '../plan'
import { signedOut } from '../session'

// The pages of a hosted app's accounts: sign in, sign up (confirmed by a mailed link), a new
// password by mail, and the account itself (sign out, delete everything).

const REASONS = new Set(['credentials', 'unverified', 'closed', 'email', 'password', 'link', 'terms', 'too_many', 'billing'])

function reason(err: unknown): string {
  return err instanceof ApiError && err.detail && REASONS.has(err.detail) ? err.detail : 'other'
}

/** After signing in: the app appears (at ``to``, or where the reader was going). */
function useSignedIn(to?: string) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['me'] })
    if (to) navigate(to, { replace: true })
  }, [queryClient, navigate, to])
}

function Problem({ code }: { code: string }) {
  const { t } = useTranslation()
  return <p className="auth-problem" role="alert">{t(`account.errors.${code}`)}</p>
}

function EmailField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation()
  return (
    <label>
      {t('account.email')}
      <input type="email" autoComplete="email" required value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

function NewPasswordField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useTranslation()
  return (
    <label>
      {t('account.newPassword')}
      <input type="password" autoComplete="new-password" required minLength={8} value={value} onChange={(e) => onChange(e.target.value)} />
      <span className="hint">{t('account.passwordHint')}</span>
    </label>
  )
}

function Resend({ email }: { email: string }) {
  const { t } = useTranslation()
  const [sent, setSent] = useState(false)
  if (sent) return <p className="hint">{t('account.resent')}</p>
  return (
    <button type="button" onClick={() => api.resend(email).then(() => setSent(true))}>
      {t('account.resend')}
    </button>
  )
}

/** Runs a form's request, keeping its error (a reason code) and whether it is under way. */
function useSubmit(run: () => Promise<void>, wrongPassword = false) {
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await run()
    } catch (err) {
      const why = reason(err)
      setProblem(wrongPassword && why === 'credentials' ? 'wrongPassword' : why)
      setBusy(false)
    }
  }
  return { submit, problem, busy }
}

export function SignIn() {
  const { t } = useTranslation()
  const signedIn = useSignedIn()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { submit, problem, busy } = useSubmit(async () => {
    await api.signIn(email, password)
    await signedIn()
  })
  return (
    <main className="auth">
      <form className="auth-form" onSubmit={submit}>
        <h1>{t('account.signInTitle')}</h1>
        <EmailField value={email} onChange={setEmail} />
        <label>
          {t('account.password')}
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {problem && <Problem code={problem} />}
        {problem === 'unverified' && <Resend email={email} />}
        <button type="submit" className="button primary" disabled={busy}>{t('account.signIn')}</button>
        <p className="auth-links"><Link to="/forgot">{t('account.forgot')}</Link></p>
        <p className="auth-links">{t('account.noAccount')} <Link to="/signup">{t('account.signUp')}</Link></p>
      </form>
    </main>
  )
}

export function SignUp() {
  const { t, i18n } = useTranslation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [terms, setTerms] = useState(false)
  const [sentTo, setSentTo] = useState<string | null>(null)
  const { submit, problem, busy } = useSubmit(async () => {
    await api.signUp(email, password, i18n.resolvedLanguage ?? 'en', terms)
    setSentTo(email.trim())
  })
  if (sentTo) {
    return (
      <main className="auth">
        <div className="auth-form">
          <h1>{t('account.signUpTitle')}</h1>
          <p>{t('account.checkEmail', { email: sentTo })}</p>
          <Resend email={sentTo} />
          <p className="auth-links"><Link to="/">{t('account.back')}</Link></p>
        </div>
      </main>
    )
  }
  return (
    <main className="auth">
      <form className="auth-form" onSubmit={submit}>
        <h1>{t('account.signUpTitle')}</h1>
        <EmailField value={email} onChange={setEmail} />
        <NewPasswordField value={password} onChange={setPassword} />
        <label className="statement">
          <input type="checkbox" required checked={terms} onChange={(e) => setTerms(e.target.checked)} />
          {/* The texts open beside the form, so nothing typed in it is lost. */}
          <span>
            <Trans i18nKey="account.acceptTerms" components={{
              terms: <Link to="/terms" target="_blank" />,
              privacy: <Link to="/privacy" target="_blank" />,
            }} />
          </span>
        </label>
        {problem && <Problem code={problem} />}
        <button type="submit" className="button primary" disabled={busy}>{t('account.signUp')}</button>
        <p className="auth-links">{t('account.haveAccount')} <Link to="/">{t('account.signIn')}</Link></p>
      </form>
    </main>
  )
}

/** The page a sign-up link opens: it confirms the email and signs the reader in. */
export function Verify() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const signedIn = useSignedIn('/')
  const [problem, setProblem] = useState<string | null>(null)
  // A link works once: never send it twice (React runs effects twice while developing).
  const sent = useRef(false)
  useEffect(() => {
    if (sent.current) return
    sent.current = true
    api.verify(params.get('token') ?? '').then(signedIn, (err) => setProblem(reason(err)))
  }, [params, signedIn])
  return (
    <main className="auth">
      <div className="auth-form">
        <h1>{t('account.signUpTitle')}</h1>
        {problem ? <Problem code={problem} /> : <p className="notice">{t('account.verifying')}</p>}
        {problem && <p className="auth-links"><Link to="/">{t('account.back')}</Link></p>}
      </div>
    </main>
  )
}

export function Forgot() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const { submit, busy } = useSubmit(async () => {
    await api.forgot(email)
    setSentTo(email.trim())
  })
  return (
    <main className="auth">
      <form className="auth-form" onSubmit={submit}>
        <h1>{t('account.forgotTitle')}</h1>
        {sentTo ? (
          <p>{t('account.forgotSent', { email: sentTo })}</p>
        ) : (
          <>
            <p className="hint">{t('account.forgotText')}</p>
            <EmailField value={email} onChange={setEmail} />
            <button type="submit" className="button primary" disabled={busy}>{t('account.sendLink')}</button>
          </>
        )}
        <p className="auth-links"><Link to="/">{t('account.back')}</Link></p>
      </form>
    </main>
  )
}

/** The page a reset link opens: a new password, and the reader is signed in with it. */
export function Reset() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const signedIn = useSignedIn('/')
  const [password, setPassword] = useState('')
  const { submit, problem, busy } = useSubmit(async () => {
    await api.reset(params.get('token') ?? '', password)
    await signedIn()
  })
  return (
    <main className="auth">
      <form className="auth-form" onSubmit={submit}>
        <h1>{t('account.resetTitle')}</h1>
        <NewPasswordField value={password} onChange={setPassword} />
        {problem && <Problem code={problem} />}
        {problem === 'link' && <p className="auth-links"><Link to="/forgot">{t('account.sendLink')}</Link></p>}
        <button type="submit" className="button primary" disabled={busy}>{t('account.save')}</button>
      </form>
    </main>
  )
}

/** The account's plan, and Paddle's customer portal for a subscription: invoices, the card, cancelling. */
function PlanSection() {
  const { t, i18n } = useTranslation()
  const plan = usePlan()
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  if (!plan || !(plan.selling || plan.manage)) return null
  const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(i18n.resolvedLanguage) : '…')
  const portal = async (page: 'overview' | 'cancel') => {
    setBusy(true)
    setProblem(null)
    try {
      const links = await api.portal()
      leaveFor((page === 'cancel' && links.cancel) || links.overview)
    } catch (err) {
      setProblem(reason(err))
    }
    setBusy(false)
  }
  const status = !plan.plus ? t('plans.onFree')
    : plan.cancel_at ? t('plans.plusEnds', { date: date(plan.cancel_at) })
    : plan.status === 'past_due' ? t('plans.pastDue')
    : t('plans.plusRenews', { date: date(plan.until) })
  return (
    <section>
      <h2>{t('plans.yours')}</h2>
      <p>{status}</p>
      <div className="plan-actions">
        {plan.checkout && <Link className="button primary" to="/plans">{t('plans.seePlus')}</Link>}
        {plan.manage && <button type="button" disabled={busy} onClick={() => portal('overview')}>{t('plans.manage')}</button>}
        {plan.plus && !plan.cancel_at && <button type="button" disabled={busy} onClick={() => portal('cancel')}>{t('plans.cancel')}</button>}
      </div>
      {problem && <Problem code={problem} />}
    </section>
  )
}

export function Account() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['me'], queryFn: api.me })
  const plus = usePlan()?.plus
  const email = me.data?.user?.email ?? ''
  const [linkSent, setLinkSent] = useState(false)
  const [password, setPassword] = useState('')
  const { submit, problem, busy } = useSubmit(async () => {
    await api.deleteAccount(password)
    signedOut(queryClient)
  }, true)
  const signOut = async () => {
    await api.signOut().catch(() => undefined)
    signedOut(queryClient)
  }
  return (
    <main className="auth account">
      <h1>{t('account.title')}</h1>
      <section>
        <p>{t('account.signedInAs', { email })}</p>
        <div><button type="button" onClick={signOut}>{t('account.signOut')}</button></div>
      </section>
      <section>
        <h2>{t('account.changePassword')}</h2>
        {linkSent ? (
          <p>{t('account.forgotSent', { email })}</p>
        ) : (
          <>
            <p className="hint">{t('account.changePasswordText')}</p>
            <div><button type="button" onClick={() => api.forgot(email).then(() => setLinkSent(true))}>{t('account.sendLink')}</button></div>
          </>
        )}
      </section>
      <PlanSection />
      <section className="account-danger">
        <h2>{t('account.deleteTitle')}</h2>
        <p>{t('account.deleteText')}</p>
        {plus && <p>{t('account.deletePlus')}</p>}
        <form className="auth-form" onSubmit={submit}>
          <label>
            {t('account.deletePassword')}
            <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {problem && <Problem code={problem} />}
          <div><button type="submit" className="danger" disabled={busy}>{t('account.deleteConfirm')}</button></div>
        </form>
      </section>
    </main>
  )
}
