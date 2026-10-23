// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Legal, Me } from './api'
import { Shell } from './App'
import { Markdown } from './components/Markdown'
import i18n from './i18n'

let me: Me
const sent: { url: string; body: unknown }[] = []
const LEGAL: Legal = {
  site: 'https://chess.example', operator: 'Ana Reader', address: null, contact: 'privacy@chess.example',
  copyright_email: 'copyright@chess.example', copyright_agent: 'Ana Reader, Calle 1, CDMX, +52 55 0000 0000',
  strikes: 3, keep_days: 30, wait_days: 15, session_days: 30, unverified_days: 7, render_days: 7,
}

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

beforeEach(async () => {
  await i18n.changeLanguage('en')
  me = { hosted: true, user: null }
  sent.length = 0
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') sent.push({ url, body: init.body ? JSON.parse(String(init.body)) : null })
    if (url === '/api/auth/me') return json(me)
    if (url === '/api/legal') return json(LEGAL)
    if (url === '/api/auth/signup') return new Response(null, { status: 204 })
    return json([])
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

describe('the legal pages', () => {
  it('are in the footer of a hosted site, also before signing in', async () => {
    at('/')
    expect((await screen.findByRole('link', { name: 'Terms' })).getAttribute('href')).toBe('/terms')
    expect(screen.getByRole('link', { name: 'Privacy' }).getAttribute('href')).toBe('/privacy')
    expect(screen.getByRole('link', { name: 'Copyright' }).getAttribute('href')).toBe('/copyright/policy')
  })

  it("aren't in the local app, which nobody else uses", async () => {
    me = { hosted: false, user: null }
    at('/')
    await screen.findByText(/Import a book/)
    expect(screen.queryByRole('link', { name: 'Terms' })).toBeNull()
    expect(screen.queryByRole('link', { name: 'Privacy' })).toBeNull()
  })

  it('fill in who runs the site, and show what is not set yet', async () => {
    at('/privacy')
    expect(await screen.findByRole('heading', { level: 1, name: 'Privacy notice' })).toBeTruthy()
    expect(screen.getByText(/^Ana Reader, at/)).toBeTruthy()
    expect(screen.getAllByRole('link', { name: 'privacy@chess.example' })[0].getAttribute('href')).toBe('mailto:privacy@chess.example')
    expect(screen.getAllByText('[CBV_OPERATOR_ADDRESS]').length).toBeGreaterThan(0)
    expect(screen.getByText(/deleted after 7 days/)).toBeTruthy()
  })

  it('are in Spanish too', async () => {
    await i18n.changeLanguage('es')
    at('/terms')
    expect(await screen.findByRole('heading', { level: 1, name: 'Términos de uso' })).toBeTruthy()
    expect(screen.getByText(/cerramos las cuentas que acumulan 3 amonestaciones/)).toBeTruthy()
    expect(screen.getAllByRole('link', { name: 'Aviso de privacidad' })[0].getAttribute('href')).toBe('/privacy')
  })

  it('the copyright policy names the agent and leads to the notice form', async () => {
    at('/copyright/policy')
    expect(await screen.findByText(/Ana Reader, Calle 1, CDMX, \+52 55 0000 0000/)).toBeTruthy()
    expect(screen.getByText(/within the next 15 business days/)).toBeTruthy()
    fireEvent.click(screen.getByRole('link', { name: 'Send a notice' }))
    expect(await screen.findByRole('heading', { name: 'Report a copyright problem' })).toBeTruthy()
  })
})

describe('signing up', () => {
  it('accepts the terms, which open beside the form', async () => {
    at('/signup')
    fireEvent.change(await screen.findByLabelText('Email'), { target: { value: 'ana@example.com' } })
    fireEvent.change(screen.getByLabelText(/New password/), { target: { value: 'correct horse' } })
    const accept = screen.getByRole('checkbox', { name: /I accept the Terms of use/ })
    expect(accept).toHaveProperty('required', true)
    const terms = screen.getByRole('link', { name: 'Terms of use' })
    expect(terms.getAttribute('href')).toBe('/terms')
    expect(terms.getAttribute('target')).toBe('_blank')
    fireEvent.click(accept)
    fireEvent.click(screen.getByRole('button', { name: 'Create an account' }))
    expect(await screen.findByText(/we've sent a link to ana@example.com/)).toBeTruthy()
    expect(sent.at(-1)).toMatchObject({ url: '/api/auth/signup', body: { email: 'ana@example.com', terms: true } })
  })
})

describe('the Markdown renderer', () => {
  it('makes links only to the site, https and mail', () => {
    render(
      <MemoryRouter>
        <Markdown text={'[in](/terms) [out](https://example.org) [bad](javascript:alert(1)) **{who}** `cbv_session`'} values={{ who: 'Ana' }} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('link', { name: 'in' }).getAttribute('href')).toBe('/terms')
    expect(screen.getByRole('link', { name: 'out' }).getAttribute('href')).toBe('https://example.org')
    expect(screen.queryByRole('link', { name: 'bad' })).toBeNull()
    expect(screen.getByText('Ana').tagName).toBe('STRONG')
    expect(screen.getByText('cbv_session').tagName).toBe('CODE')
  })
})
