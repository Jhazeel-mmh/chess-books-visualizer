// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { BookMeta, Me } from './api'
import { Shell } from './App'
import i18n from './i18n'

let me: Me
let books: BookMeta[]
let uploadStatus = 200
const sent: { url: string; body: unknown }[] = []

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const book = (changes: Partial<BookMeta> = {}): BookMeta => ({
  id: 'a'.repeat(40), title: 'Ajedrez Táctico', filename: 'Ajedrez Táctico.epub', format: 'epub', status: 'ready',
  error: null, stats: null, imported_at: '2026-10-01T10:00:00+00:00', ...changes,
})
const DISABLED = { at: '2026-10-18T12:00:00+00:00', claimant: 'Example Chess Publishing', work: 'Ajedrez Táctico, by A. Author' }

beforeAll(async () => {
  await i18n.changeLanguage('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const body = init?.body instanceof FormData ? Object.fromEntries(init.body) : init?.body ? JSON.parse(String(init.body)) : null
    if (init?.method === 'POST') sent.push({ url, body })
    if (url === '/api/auth/me') return json(me)
    if (url === '/api/auth/login') return json({ detail: 'closed' }, 403)
    if (url === '/api/books' && init?.method === 'POST') return uploadStatus === 200 ? json(book()) : json({ detail: 'blocked' }, uploadStatus)
    if (url === '/api/books') return json(books)
    if (url.startsWith('/api/books/') && url.endsWith('/counter-notice')) {
      books = books.map((b) => ({ ...b, disabled: { ...DISABLED, counter_at: '2026-10-19T09:00:00+00:00' } }))
      return new Response(null, { status: 204 })
    }
    if (url.startsWith('/api/books/')) return json(books[0])
    if (url === '/api/copyright-notices') return json({ id: 7 }, 201)
    return json({})
  }))
})
beforeEach(() => {
  me = { hosted: true, user: { email: 'ana@example.com' } }
  books = []
  uploadStatus = 200
  sent.length = 0
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

const fill = (label: string | RegExp, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })

describe('uploading to the site', () => {
  it('first asks the reader to say the book is theirs to use', async () => {
    at('/')
    const declaration = await screen.findByLabelText(/I own this book or have the right to use it/)
    const input = document.querySelector<HTMLInputElement>('input[type=file]')!
    expect(input.disabled).toBe(true)

    fireEvent.click(declaration)
    expect(input.disabled).toBe(false)
    fireEvent.change(input, { target: { files: [new File(['%PDF'], 'mine.pdf')] } })
    await vi.waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]).toMatchObject({ url: '/api/books', body: { rights: 'true' } })
  })

  it('says when a file was blocked after a copyright notice', async () => {
    uploadStatus = 451
    at('/')
    fireEvent.click(await screen.findByLabelText(/I own this book/))
    fireEvent.change(document.querySelector('input[type=file]')!, { target: { files: [new File(['%PDF'], 'mine.pdf')] } })
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', "This file can't be uploaded here because of a copyright notice.")
  })

  it('the local app asks nothing and has no copyright page', async () => {
    me = { hosted: false, user: null }
    at('/')
    await screen.findByText(/Import a book/)
    expect(screen.queryByLabelText(/I own this book/)).toBeNull()
    expect(document.querySelector<HTMLInputElement>('input[type=file]')!.disabled).toBe(false)
    expect(screen.queryByRole('link', { name: 'Copyright' })).toBeNull()
  })
})

describe('a disabled book', () => {
  it('stays listed, says why, and can only be answered or deleted', async () => {
    books = [book({ disabled: DISABLED })]
    at('/')
    const row = (await screen.findByText('Ajedrez Táctico')).closest('li')!
    expect(within(row).getByText('Disabled')).toBeTruthy()
    expect(within(row).getByText(/after a copyright notice sent on behalf of Example Chess Publishing/)).toBeTruthy()
    expect(within(row).queryByRole('link', { name: 'Read' })).toBeNull()
    expect(within(row).queryByRole('button', { name: 'Analyze again' })).toBeNull()
    expect(within(row).getByRole('button', { name: 'Delete' })).toBeTruthy()
    expect(within(row).getByRole('link', { name: 'Send a counter-notice' }).getAttribute('href')).toBe(`/copyright/counter/${'a'.repeat(40)}`)
  })

  it('takes a counter-notice from its owner', async () => {
    books = [book({ disabled: DISABLED })]
    at(`/copyright/counter/${'a'.repeat(40)}`)
    expect(await screen.findByText(/“Ajedrez Táctico” was disabled in your library/)).toBeTruthy()
    expect(screen.getByText(DISABLED.work)).toBeTruthy()
    fill('Your full name', 'Ana Reader')
    fill('Postal address', 'Calle 1, CDMX')
    fill('Phone', '+52 55 0000 0000')
    fill(/Why/, 'I bought this ebook.')
    fireEvent.click(screen.getByLabelText(/I believe in good faith that the material was disabled/))
    fireEvent.click(screen.getByLabelText(/I consent to the jurisdiction/))
    fill(/Signature/, 'Ana Reader')
    fireEvent.click(screen.getByRole('button', { name: 'Send the counter-notice' }))
    expect(await screen.findByText(/You sent a counter-notice on/)).toBeTruthy()
    expect(sent.at(-1)).toMatchObject({
      url: `/api/books/${'a'.repeat(40)}/counter-notice`,
      body: { name: 'Ana Reader', phone: '+52 55 0000 0000', good_faith: true, jurisdiction: true, lang: 'en' },
    })
  })

  it("can't be opened in the reader", async () => {
    books = [book({ disabled: DISABLED })]
    at(`/books/${'a'.repeat(40)}`)
    expect(await screen.findByText(/This book was disabled after a copyright notice/)).toBeTruthy()
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/analysis'))).toBe(false)
  })
})

describe('the copyright notice form', () => {
  it('is open to anyone, and sends only the fingerprint of the file', async () => {
    me = { hosted: true, user: null }
    at('/licenses')
    // The footer leads to the copyright policy, and the policy to the form.
    fireEvent.click(await screen.findByRole('link', { name: 'Copyright' }))
    fireEvent.click(await screen.findByRole('link', { name: 'Send a notice' }))
    await screen.findByRole('heading', { name: 'Report a copyright problem' })
    fill('Your full name', 'Rita Agent')
    fill('Email', 'rita@publisher.example')
    fill('Postal address', '1 Book St, Springfield')
    fill(/Rights holder/, 'Example Chess Publishing')
    fill(/Which work/, 'Ajedrez Táctico, by A. Author')
    // Its SHA-256, worked out apart: python3 -c "import hashlib; print(hashlib.sha256('the publisher’s copy'.encode()).hexdigest())"
    const bytes = 'the publisher’s copy'
    fireEvent.change(screen.getByLabelText(/Your copy of the file/), { target: { files: [new File([bytes], 'book.epub')] } })
    fireEvent.click(screen.getByLabelText(/I believe in good faith that the use of the material/))
    fireEvent.click(screen.getByLabelText(/under penalty of perjury, I am the rights holder/))
    fill(/Signature/, 'Rita Agent')
    fireEvent.click(screen.getByRole('button', { name: 'Send the notice' }))

    expect(await screen.findByText(/notice #7 is received/)).toBeTruthy()
    const [notice] = sent
    expect(notice.url).toBe('/api/copyright-notices')
    expect(notice.body).toMatchObject({
      name: 'Rita Agent', claimant: 'Example Chess Publishing', phone: '', good_faith: true, accurate: true,
      sha256: '4aecfd7edc53dbc87bed825462a6e89145920dff5d5cba9356bdca6cef2534b0',
    })
  })
})

describe('a closed account', () => {
  it('is told so when signing in', async () => {
    me = { hosted: true, user: null }
    at('/')
    await screen.findByLabelText('Email')
    fill('Email', 'ana@example.com')
    fill('Password', 'correct horse')
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'This account is closed. We sent the reason by email.')
  })
})
