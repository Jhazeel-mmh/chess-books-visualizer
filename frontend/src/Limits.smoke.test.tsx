// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BookMeta, Me, Usage } from './api'
import { Shell } from './App'
import i18n from './i18n'

const MB = 2 ** 20
let me: Me
let books: BookMeta[]
let refusal: { status: number; detail: string } | null
const posted: string[] = []

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const USAGE: Usage = { books: 2, bytes: 12.4 * MB, max_books: 50, max_bytes: 1000 * MB, max_upload: 100 * MB }

beforeAll(async () => {
  await i18n.changeLanguage('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') posted.push(url)
    if (url === '/api/auth/me') return json(me)
    if (url === '/api/auth/login') return json({ detail: 'too_many' }, 429)
    if (url === '/api/usage') return json(USAGE)
    if (url === '/api/books' && init?.method === 'POST') return refusal ? json({ detail: refusal.detail }, refusal.status) : json(books[0])
    if (url === '/api/books') return json(books)
    return json({})
  }))
})
beforeEach(() => {
  me = { hosted: true, user: { email: 'ana@example.com' } }
  books = []
  refusal = null
  posted.length = 0
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

async function choose(file: File) {
  fireEvent.click(await screen.findByLabelText(/I own this book/))
  fireEvent.change(document.querySelector('input[type=file]')!, { target: { files: [file] } })
}

describe('what an account may keep', () => {
  it('shows how much of it the library uses', async () => {
    at('/')
    expect(await screen.findByText('2 of 50 books · 13 of 1000 MB · up to 100 MB per book')).toBeTruthy()
  })

  it("doesn't send a file over the size limit", async () => {
    at('/')
    await screen.findByText(/of 50 books/)
    const big = new File(['%PDF'], 'big.pdf')
    Object.defineProperty(big, 'size', { value: 150 * MB })
    await choose(big)
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'This file is larger than 100 MB, the most a book can be here.')
    expect(posted).toEqual([])
  })

  it('says why the server refused a book', async () => {
    refusal = { status: 403, detail: 'books' }
    at('/')
    await screen.findByText(/of 50 books/)
    await choose(new File(['%PDF'], 'one more.pdf'))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Your library is full (50 books). Delete a book to make room for this one.')
  })

  it('the local app shows no limits', async () => {
    me = { hosted: false, user: null }
    at('/')
    await screen.findByText(/Import a book/)
    expect(screen.queryByText(/of 50 books/)).toBeNull()
    expect(vi.mocked(fetch).mock.calls.some(([url]) => url === '/api/usage')).toBe(false)
  })
})

describe('limits on the work and the tries', () => {
  it('says when reading a book was stopped', async () => {
    books = [{
      id: 'a'.repeat(40), title: 'Huge scan', filename: 'Huge scan.pdf', format: 'pdf', status: 'error',
      error: 'limit: time', stats: null, imported_at: '2026-10-01T10:00:00+00:00',
    }]
    at('/')
    expect(await screen.findByText('Reading this book took too long, so it was stopped.')).toBeTruthy()
  })

  it('asks to wait after too many tries', async () => {
    me = { hosted: true, user: null }
    at('/')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong guess' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Too many tries. Wait a few minutes and try again.')
  })
})
