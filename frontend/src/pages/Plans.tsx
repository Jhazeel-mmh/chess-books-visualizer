import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type Price } from '../api'
import { buyPlus, money, payTransaction, usePlan } from '../plan'

// A hosted site's plans, for anyone: what the free plan and Plus give, and Plus's price, as
// Paddle has it. A signed-in free account buys Plus here.

type T = ReturnType<typeof useTranslation>['t']

const space = (mb: number) => (mb >= 1000 ? `${(mb / 1000).toLocaleString()} GB` : `${mb} MB`)

function priceText(t: T, price: Price, lang?: string): string {
  const amount = money(price, lang)
  return price.interval ? `${amount} ${t(`plans.every.${price.interval}`, { count: price.frequency ?? 1 })}` : amount
}

export function Plans() {
  const { t, i18n } = useTranslation()
  const plans = useQuery({ queryKey: ['plans'], queryFn: api.plans }).data
  // Paddle's own links (to the default payment link) open their checkout here, once.
  const transaction = useSearchParams()[0].get('_ptxn')
  const opened = useRef(false)
  useEffect(() => {
    if (!transaction || !plans?.paddle || opened.current) return
    opened.current = true
    payTransaction(plans.paddle, transaction, i18n.resolvedLanguage ?? 'en').catch(() => undefined)
  }, [transaction, plans?.paddle, i18n.resolvedLanguage])
  if (!plans) return <main className="plans"><p className="notice">…</p></main>
  const { free, plus, price, selling, ads } = plans
  const books = (count: number) => (count ? t('plans.books', { count }) : t('plans.anyBooks'))
  const storage = (mb: number) => (mb ? t('plans.storage', { size: space(mb) }) : t('plans.anyStorage'))

  return (
    <main className="plans">
      <h1>{t('plans.title')}</h1>
      <div className="plan-cards">
        <section className="plan-card">
          <h2>{t('plans.free')}</h2>
          <p className="plan-price">{t('plans.freePrice')}</p>
          <ul>
            <li>{books(free.books)}</li>
            <li>{storage(free.storage_mb)}</li>
            <li>{t('plans.reading')}</li>
            <li>{free.trainer_sessions ? t('plans.trainerTrial', { count: free.trainer_sessions }) : t('plans.trainer')}</li>
            {ads && <li>{t('plans.withAds')}</li>}
          </ul>
        </section>
        {selling && (
          <section className="plan-card plus">
            <h2>{t('plans.plus')}</h2>
            <p className="plan-price">{price ? priceText(t, price, i18n.resolvedLanguage) : '…'}</p>
            {price?.trial_interval && (
              <p className="hint">{t(`plans.trial.${price.trial_interval}`, { count: price.trial_frequency ?? 1 })}</p>
            )}
            <ul>
              <li>{books(plus.books)}</li>
              <li>{storage(plus.storage_mb)}</li>
              <li>{t('plans.reading')}</li>
              <li>{t('plans.trainer')}</li>
              {ads && <li>{t('plans.noAds')}</li>}
            </ul>
            <GetPlus />
          </section>
        )}
      </div>
      {selling && (
        <p className="hint">
          <Trans i18nKey="plans.sold" components={{ terms: <Link to="/terms" /> }} />
        </p>
      )}
      {selling && <p className="hint">{t('plans.lapse')}</p>}
      <p className="hint">{t('plans.upload', { size: space(plans.upload_mb) })}</p>
    </main>
  )
}

/** Buying Plus: an account first; then Paddle's checkout, over this page. */
function GetPlus() {
  const { t, i18n } = useTranslation()
  const signedIn = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity }).data?.user != null
  const plan = usePlan()
  const [state, setState] = useState<'idle' | 'opening' | 'paid' | 'failed'>('idle')
  // Paddle tells the server a moment after the payment: until then, ask again every two seconds.
  useQuery({ queryKey: ['plan'], queryFn: api.plan, enabled: state === 'paid' && !plan?.plus, refetchInterval: 2000 })

  if (!signedIn) return <Link className="button primary" to="/signup">{t('plans.signUpFirst')}</Link>
  if (plan?.plus) return <p className="notice">{t('plans.youHavePlus')} <Link to="/account">{t('account.title')}</Link></p>
  if (state === 'paid') return <p className="notice">{t('plans.thanks')}</p>
  const checkout = plan?.checkout
  if (!checkout) return null
  const buy = () => {
    setState('opening')
    buyPlus(checkout, i18n.resolvedLanguage ?? 'en', () => setState('paid')).then(
      () => setState((s) => (s === 'opening' ? 'idle' : s)),
      () => setState('failed'),
    )
  }
  return (
    <>
      <button type="button" className="primary" disabled={state === 'opening'} onClick={buy}>{t('plans.getPlus')}</button>
      {state === 'failed' && <p className="auth-problem" role="alert">{t('plans.failed')}</p>}
    </>
  )
}
