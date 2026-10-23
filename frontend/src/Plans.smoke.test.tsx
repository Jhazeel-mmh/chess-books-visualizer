// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Me, Plan, Plans, TrainerRecord } from './api'
import { Shell } from './App'
import i18n from './i18n'

const paddle = vi.hoisted(() => ({ buyPlus: vi.fn(), leaveFor: vi.fn(), payTransaction: vi.fn() }))
vi.mock('./plan', async (original) => ({ ...(await original<typeof import('./plan')>()), ...paddle }))

const CHECKOUT = { token: 'test_token', price: 'pri_plus', sandbox: true, email: 'ana@example.com', user: 'a'.repeat(32) }
const FREE: Plan = {
  plus: false, status: null, until: null, cancel_at: null, selling: true, manage: false, checkout: CHECKOUT,
  ads: { client: 'ca-pub-123', slot: '456' }, trainer_left: 7,
}
const PLUS: Plan = {
  ...FREE, plus: true, status: 'active', until: '2026-11-21T10:00:00Z', manage: true, checkout: null, ads: null, trainer_left: null,
}
const PLANS: Plans = {
  selling: true, ads: true, upload_mb: 100, paddle: { token: 'test_token', sandbox: true },
  price: { amount: '500', currency: 'USD', interval: 'month', frequency: 1, trial_interval: null, trial_frequency: null },
  free: { books: 3, storage_mb: 300, trainer_sessions: 7 }, plus: { books: 300, storage_mb: 5000 },
}
const RECORD: TrainerRecord = {
  settings: { minutes: 50, rating: 1800, focus: null }, level: null, roles: {}, positions: {},
  reading: { book: null, at: {} }, games: { current: null, at: {} }, sources: {}, sessions: [], current: null,
}

let me: Me
let plan: Plan
let upload: { status: number; detail: string } | null
const asked: string[] = []

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(async () => {
  await i18n.changeLanguage('en')
  me = { hosted: true, user: { email: 'ana@example.com' } }
  plan = FREE
  upload = null
  asked.length = 0
  paddle.buyPlus.mockReset().mockResolvedValue(undefined)
  paddle.leaveFor.mockReset()
  paddle.payTransaction.mockReset().mockResolvedValue(undefined)
  document.head.querySelectorAll('script').forEach((s) => s.remove())
  delete window.adsbygoogle
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    asked.push(`${init?.method ?? 'GET'} ${url}`)
    if (url === '/api/auth/me') return json(me)
    if (url === '/api/plan') return json(plan)
    if (url === '/api/plans') return json(PLANS)
    if (url === '/api/billing/portal') return json({ overview: 'https://customer-portal.paddle.com/o', cancel: 'https://customer-portal.paddle.com/c' })
    if (url === '/api/books' && init?.method === 'POST') return upload ? json({ detail: upload.detail }, upload.status) : json({})
    if (url === '/api/books') return json([])
    if (url === '/api/usage') return json({ books: 3, bytes: 0, max_books: 3, max_bytes: 300 * 2 ** 20, max_upload: 100 * 2 ** 20 })
    if (url === '/api/trainer') return json(RECORD)
    if (url === '/api/trainer/books') return json([])
    return json({})
  }))
})
afterEach(cleanup)

function at(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><Shell /></MemoryRouter>
    </QueryClientProvider>,
  )
}

const SOURCES = import.meta.glob<string>('./**/*.tsx', { query: '?raw', import: 'default', eager: true })

describe('ads', () => {
  it('are only on pages that show nothing of a book', () => {
    const pages = Object.entries(SOURCES).filter(([path, src]) => !path.includes('.test.') && src.includes('<AdSlot')).map(([path]) => path)
    expect(pages.sort()).toEqual(['./pages/Library.tsx', './pages/Trainer.tsx'])
    // In the trainer: its start page and a session's summary, never a block with positions or a book.
    const trainer = SOURCES['./pages/Trainer.tsx'].split('\nfunction ')
    expect(trainer.filter((f) => f.includes('<AdSlot')).map((f) => f.split('(')[0])).toEqual(['Home', 'Summary'])
  })

  it('show to a free account, labelled, from one script', async () => {
    at('/')
    await waitFor(() => expect(document.querySelector('ins.adsbygoogle')).toBeTruthy())
    const ad = document.querySelector('ins.adsbygoogle')!
    expect(ad.getAttribute('data-ad-client')).toBe('ca-pub-123')
    expect(ad.getAttribute('data-ad-slot')).toBe('456')
    expect(screen.getByText('Advertisement')).toBeTruthy()
    const scripts = document.head.querySelectorAll('script[src^="https://pagead2.googlesyndication.com/"]')
    expect([...scripts].map((s) => s.getAttribute('src'))).toEqual(['https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-123'])
    expect(window.adsbygoogle).toHaveLength(1)
  })

  it("don't show to Plus, nor in the local app", async () => {
    plan = PLUS
    at('/')
    await screen.findByText(/Import a book/)
    await waitFor(() => expect(asked).toContain('GET /api/plan'))
    expect(document.querySelector('ins.adsbygoogle')).toBeNull()
    cleanup()

    me = { hosted: false, user: null }
    asked.length = 0
    at('/')
    await screen.findByText(/Import a book/)
    expect(document.querySelector('ins.adsbygoogle')).toBeNull()
    expect(asked).not.toContain('GET /api/plan')
  })
})

describe('the plans page', () => {
  it('shows both plans and the price to anyone', async () => {
    me = { hosted: true, user: null }
    at('/plans')
    expect(await screen.findByRole('heading', { level: 1, name: 'Plans' })).toBeTruthy()
    expect(screen.getByText('$5.00 per month')).toBeTruthy()
    expect(screen.getByText('3 books in your library')).toBeTruthy()
    expect(screen.getByText('300 books in your library')).toBeTruthy()
    expect(screen.getByText('5 GB for your book files')).toBeTruthy()
    expect(screen.getByText('7 daily-trainer sessions to try it')).toBeTruthy()
    expect(screen.getByText(/sold by Paddle.com/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Create an account to get Plus' }).getAttribute('href')).toBe('/signup')
    expect(screen.getByRole('link', { name: 'Plans' }).getAttribute('href')).toBe('/plans') // in the footer
  })

  it("opens Paddle's checkout, and Plus starts once Paddle says it was paid", async () => {
    at('/plans')
    fireEvent.click(await screen.findByRole('button', { name: 'Get Plus' }))
    await waitFor(() => expect(paddle.buyPlus).toHaveBeenCalled())
    const [checkout, lang, paid] = paddle.buyPlus.mock.calls[0]
    expect(checkout).toEqual(CHECKOUT)
    expect(lang).toBe('en')
    plan = PLUS
    paid()
    expect(await screen.findByText(/You have Plus/, {}, { timeout: 5000 })).toBeTruthy()
  })

  it("opens the checkouts Paddle links to (a new card, say)", async () => {
    at('/plans?_ptxn=txn_01')
    await waitFor(() => expect(paddle.payTransaction).toHaveBeenCalledWith({ token: 'test_token', sandbox: true }, 'txn_01', 'en'))
  })
})

describe('the account', () => {
  it('cancels Plus in one click, in Paddle’s portal', async () => {
    plan = PLUS
    at('/account')
    expect(await screen.findByText(`You have Plus. It renews on ${new Date('2026-11-21T10:00:00Z').toLocaleDateString('en')}.`)).toBeTruthy()
    expect(screen.getByText(/Your Plus subscription is cancelled with it/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel subscription' }))
    await waitFor(() => expect(paddle.leaveFor).toHaveBeenCalledWith('https://customer-portal.paddle.com/c'))
    expect(asked).toContain('POST /api/billing/portal')
  })

  it('shows the free plan and leads to Plus', async () => {
    at('/account')
    expect(await screen.findByText("You're on the free plan.")).toBeTruthy()
    expect(screen.getByRole('link', { name: 'See Plus' }).getAttribute('href')).toBe('/plans')
    expect(screen.queryByRole('button', { name: 'Cancel subscription' })).toBeNull()
  })
})

describe('the free plan', () => {
  it('counts the trainer sessions left, and leads to Plus when they are spent', async () => {
    plan = { ...FREE, trainer_left: 2 }
    at('/train')
    expect(await screen.findByText('2 free sessions left to try the trainer.')).toBeTruthy()
    cleanup()

    plan = { ...FREE, trainer_left: 0 }
    at('/train')
    expect(await screen.findByText(/You've used your free sessions/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'See Plus' }).getAttribute('href')).toBe('/plans')
    expect(screen.queryByRole('button', { name: /Start a/ })).toBeNull()
  })

  it('points a full library to Plus', async () => {
    upload = { status: 403, detail: 'books' }
    at('/')
    fireEvent.click(await screen.findByLabelText(/I own this book/))
    fireEvent.change(document.querySelector('input[type=file]')!, { target: { files: [new File(['x'], 'b.epub')] } })
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Plus has room for more books.' }).getAttribute('href')).toBe('/plans')
  })
})
