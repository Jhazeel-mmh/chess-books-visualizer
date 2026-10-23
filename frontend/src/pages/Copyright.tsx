import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'

// Copyright on the hosted app: the notice a rights holder sends about books uploaded here, and the
// counter-notice the owner of a disabled book may answer with (see backend/cbv/copyright.py).

/** The SHA-256 of a file, worked out here: only this fingerprint is sent, never the file. */
async function fingerprint(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** A form's text fields: their values, and the props that tie an input to one of them. */
function useFields<K extends string>(names: readonly K[]) {
  const [values, setValues] = useState(() => Object.fromEntries(names.map((n) => [n, ''])) as Record<K, string>)
  const bind = (name: K) => ({
    value: values[name],
    onChange: (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setValues((v) => ({ ...v, [name]: e.target.value })),
  })
  return [values, bind] as const
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label>
      {label}
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  )
}

/** A statement the sender makes: the form goes only with it checked. */
function Statement({ text }: { text: string }) {
  return (
    <label className="statement">
      <input type="checkbox" required />
      <span>{text}</span>
    </label>
  )
}

const day = (iso: string, lang?: string) => new Date(iso).toLocaleDateString(lang)

export function CopyrightNotice() {
  const { t, i18n } = useTranslation()
  const [v, bind] = useFields(['name', 'email', 'phone', 'address', 'claimant', 'work', 'location', 'signature'] as const)
  const [file, setFile] = useState<File | null>(null)
  const [sent, setSent] = useState<number | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      const sha256 = file ? await fingerprint(file) : null
      const { id } = await api.copyrightNotice({ ...v, sha256, good_faith: true, accurate: true, lang: i18n.resolvedLanguage ?? 'en' })
      setSent(id)
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail === 'too_many' ? 'account.errors.too_many' : 'account.errors.other')
      setBusy(false)
    }
  }

  return (
    <main className="auth copyright">
      <h1>{t('copyright.title')}</h1>
      {sent != null ? (
        <p>{t('copyright.sent', { id: sent, email: v.email.trim() })}</p>
      ) : (
        <>
          <p>{t('copyright.intro')}</p>
          <p className="hint">{t('copyright.private')} <Link to="/copyright/policy">{t('copyright.policyLink')}</Link></p>
          <form className="auth-form" onSubmit={submit}>
            <fieldset>
              <legend>{t('copyright.you')}</legend>
              <Field label={t('copyright.name')}><input required autoComplete="name" maxLength={200} {...bind('name')} /></Field>
              <Field label={t('account.email')}><input type="email" required autoComplete="email" maxLength={254} {...bind('email')} /></Field>
              <Field label={t('copyright.phone')} hint={t('copyright.optional')}><input type="tel" autoComplete="tel" maxLength={50} {...bind('phone')} /></Field>
              <Field label={t('copyright.address')}><textarea required rows={2} autoComplete="street-address" maxLength={500} {...bind('address')} /></Field>
              <Field label={t('copyright.claimant')} hint={t('copyright.claimantHint')}><input required maxLength={200} {...bind('claimant')} /></Field>
            </fieldset>
            <fieldset>
              <legend>{t('copyright.workLegend')}</legend>
              <Field label={t('copyright.work')} hint={t('copyright.workHint')}><textarea required rows={3} maxLength={2000} {...bind('work')} /></Field>
              <Field label={t('copyright.file')} hint={t('copyright.fileHint')}>
                <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
              </Field>
              <Field label={t('copyright.location')} hint={t('copyright.locationHint')}><textarea rows={2} maxLength={2000} {...bind('location')} /></Field>
            </fieldset>
            <Statement text={t('copyright.goodFaith')} />
            <Statement text={t('copyright.accurate')} />
            <Field label={t('copyright.signature')} hint={t('copyright.signatureHint')}><input required maxLength={200} {...bind('signature')} /></Field>
            {problem && <p className="auth-problem" role="alert">{t(problem)}</p>}
            <button type="submit" className="button primary" disabled={busy}>{t('copyright.send')}</button>
          </form>
        </>
      )}
      <p className="auth-links"><Link to="/">{t('account.back')}</Link></p>
    </main>
  )
}

/** The answer of a disabled book's owner to the notice that disabled it. */
export function CounterNotice() {
  const { id = '' } = useParams()
  const { t, i18n } = useTranslation()
  const lang = i18n.resolvedLanguage
  const queryClient = useQueryClient()
  const book = useQuery({ queryKey: ['book', id], queryFn: () => api.book(id) })
  const legal = useQuery({ queryKey: ['legal'], queryFn: api.legal, staleTime: Infinity })
  const [v, bind] = useFields(['name', 'address', 'phone', 'reason', 'signature'] as const)
  const [problem, setProblem] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setProblem(null)
    try {
      await api.counterNotice(id, { ...v, good_faith: true, jurisdiction: true, lang: lang ?? 'en' })
      await queryClient.invalidateQueries({ queryKey: ['book', id] })
      queryClient.invalidateQueries({ queryKey: ['books'] })
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail === 'sent' ? 'copyright.sentAlready' : 'account.errors.other')
    }
    setBusy(false)
  }
  const disabled = book.data?.disabled

  let body: ReactNode
  if (book.isPending) body = <p className="notice">…</p>
  else if (!disabled) body = <p>{t('copyright.notDisabled')}</p>
  else if (disabled.counter_at) body = <p>{t('copyright.counterSent', { date: day(disabled.counter_at, lang) })}</p>
  else {
    body = (
      <>
        <p>{t('copyright.counterAbout', { title: book.data?.title, date: day(disabled.at, lang), claimant: disabled.claimant })}</p>
        <blockquote>{disabled.work}</blockquote>
        <p className="hint">
          {t('copyright.counterIntro', { days: legal.data?.wait_days ?? '…' })} <Link to="/copyright/policy">{t('copyright.policyLink')}</Link>
        </p>
        <form className="auth-form" onSubmit={submit}>
          <Field label={t('copyright.name')}><input required autoComplete="name" maxLength={200} {...bind('name')} /></Field>
          <Field label={t('copyright.address')}><textarea required rows={2} autoComplete="street-address" maxLength={500} {...bind('address')} /></Field>
          <Field label={t('copyright.phone')}><input type="tel" required autoComplete="tel" maxLength={50} {...bind('phone')} /></Field>
          <Field label={t('copyright.reason')} hint={t('copyright.reasonHint')}><textarea rows={3} maxLength={2000} {...bind('reason')} /></Field>
          <Statement text={t('copyright.counterGoodFaith')} />
          <Statement text={t('copyright.jurisdiction')} />
          <Field label={t('copyright.signature')} hint={t('copyright.counterSignatureHint')}><input required maxLength={200} {...bind('signature')} /></Field>
          {problem && <p className="auth-problem" role="alert">{t(problem)}</p>}
          <button type="submit" className="button primary" disabled={busy}>{t('copyright.sendCounter')}</button>
        </form>
      </>
    )
  }

  return (
    <main className="auth copyright">
      <h1>{t('copyright.counterTitle')}</h1>
      {body}
      <p className="auth-links"><Link to="/">{t('account.back')}</Link></p>
    </main>
  )
}
