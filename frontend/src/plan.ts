import { useQuery } from '@tanstack/react-query'
import { api, type Checkout, type Paddle, type Price } from './api'

// A hosted account's plan: free, or Plus, sold by Paddle (the merchant of record). Paddle.js
// loads only when a checkout opens (the reader buys Plus, or follows a link of Paddle's), over the page.

/** The signed-in account's plan (undefined in the local app, or until it is known). */
export function usePlan() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity }).data
  return useQuery({ queryKey: ['plan'], queryFn: api.plan, enabled: me?.hosted === true && me.user != null }).data
}

/** Leaves the app for a page of Paddle's (its customer portal). */
export function leaveFor(url: string) {
  window.location.assign(url)
}

const PADDLE = 'https://cdn.paddle.com/paddle/v2/paddle.js'

interface PaddleJs {
  Environment: { set: (environment: string) => void }
  Initialize: (options: { token: string; eventCallback: (event: { name?: string }) => void }) => void
  Checkout: { open: (options: object) => void }
}

declare global {
  interface Window {
    Paddle?: PaddleJs
  }
}

let paddle: Promise<PaddleJs> | null = null
let paid = () => {}

function loadPaddle(settings: Paddle): Promise<PaddleJs> {
  paddle ??= new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = PADDLE
    script.onload = () => {
      const p = window.Paddle
      if (!p) return reject(new Error('Paddle.js'))
      if (settings.sandbox) p.Environment.set('sandbox')
      p.Initialize({ token: settings.token, eventCallback: (event) => event.name === 'checkout.completed' && paid() })
      resolve(p)
    }
    script.onerror = () => {
      paddle = null
      reject(new Error('Paddle.js'))
    }
    document.head.appendChild(script)
  })
  return paddle
}

/** Opens Paddle's checkout for Plus; ``done`` runs once the reader has paid. */
export async function buyPlus(checkout: Checkout, lang: string, done: () => void) {
  const p = await loadPaddle(checkout)
  paid = done
  p.Checkout.open({
    items: [{ priceId: checkout.price, quantity: 1 }],
    customer: { email: checkout.email },
    // Paddle keeps it on the subscription, and its webhooks name the account with it.
    customData: { user: checkout.user },
    settings: { displayMode: 'overlay', locale: lang },
  })
}

/** Opens a checkout Paddle made itself (its links to the default payment link, /plans?_ptxn=…:
 *  a new card for a subscription, say). */
export async function payTransaction(settings: Paddle, transactionId: string, lang: string) {
  const p = await loadPaddle(settings)
  paid = () => {}
  p.Checkout.open({ transactionId, settings: { displayMode: 'overlay', locale: lang } })
}

/** A price in the reader's language: "US$5.00" / "5,00 US$". */
export function money(price: Price, lang?: string): string {
  const format = new Intl.NumberFormat(lang, { style: 'currency', currency: price.currency })
  return format.format(Number(price.amount) / 10 ** (format.resolvedOptions().maximumFractionDigits ?? 2))
}
