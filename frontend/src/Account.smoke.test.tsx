// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Me } from './api'
import { Shell } from './App'
import i18n from './i18n'

let me: Me
let booksStatus = 200
const calls: string[] = []

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

beforeAll(async () => {
  await i18n.changeLanguage('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(url)
    const body = init?.body ? JSON.parse(String(init.body)) : null
    if (url === '/api/auth/me') return json(me)
    if (url === '/api/auth/login') {
      if (body.password === 'correct horse') {
        me = { hosted: true, user: { email: body.email } }
        return new Response(null, { status: 204 })
      }
      return body.password === 'not confirmed' ? json({ detail: 'unverified' }, 403) : json({ detail: 'credentials' }, 401)
    }
    if (url === '/api/auth/signup' || url === '/api/auth/resend') return new Response(null, { status: 204 })
    if (url === '/api/books') return booksStatus === 200 ? json([]) : json({ detail: 'Unauthorized' }, booksStatus)
    return json({})
  }))
})
beforeEach(() => {
  booksStatus = 200
  calls.length = 0
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

describe('the local app', () => {
  it('opens straight on the library, with no account', async () => {
    me = { hosted: false, user: null }
    at('/')
    expect(await screen.findByText(/Import a book/i)).toBeTruthy()
    expect(screen.queryByRole('link', { name: 'Account' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Sign in' })).toBeNull()
  })
})

describe('a hosted app', () => {
  it('asks who you are first, then shows your library', async () => {
    me = { hosted: true, user: null }
    at('/')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong password' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'Wrong email or password.')
    expect(calls).not.toContain('/api/books')

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'correct horse' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('link', { name: 'Account' })).toBeTruthy()
    expect(await screen.findByText(/Import a book/i)).toBeTruthy()
    expect(screen.getByText('EPUB or PDF. Only you can see your books.')).toBeTruthy()
  })

  it('offers to send the link again to an email not confirmed yet', async () => {
    me = { hosted: true, user: null }
    at('/')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'not confirmed' } })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Send the link again' }))
    expect(await screen.findByText('Sent again.')).toBeTruthy()
    expect(calls).toContain('/api/auth/resend')
  })

  it('after signing up, says to check the email', async () => {
    me = { hosted: true, user: null }
    at('/signup')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } })
    fireEvent.change(screen.getByLabelText(/New password/), { target: { value: 'correct horse' } })
    fireEvent.click(screen.getByRole('checkbox', { name: /I accept the Terms of use/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(await screen.findByText(/we've sent a link to ana@example.com/)).toBeTruthy()
  })

  it('when the session ends, goes back to sign in and forgets where this reader was', async () => {
    me = { hosted: true, user: { email: 'ana@example.com' } }
    localStorage.setItem('cbv.pos.abc', '{"page":12}')
    localStorage.setItem('cbv.zoom', '1.2')
    booksStatus = 401
    at('/')
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeTruthy()
    expect(localStorage.getItem('cbv.pos.abc')).toBeNull()
    expect(localStorage.getItem('cbv.zoom')).toBe('1.2')
  })
})
