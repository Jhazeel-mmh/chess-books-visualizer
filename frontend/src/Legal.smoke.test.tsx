// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Package } from './api'
import { Footer } from './components/Footer'
import i18n from './i18n'
import { Licenses } from './pages/Legal'

const browser: Package[] = [
  { name: 'chess.js', version: '1.4.0', license: 'BSD-2-Clause', repository: 'https://github.com/jhlywa/chess.js', text: 'Copyright (c) 2025, Jeff Hlywa' },
  { name: 'stockfish', version: '19.0.1', license: 'GPL-3.0', repository: 'https://github.com/nmrugg/stockfish.js', text: 'GNU GENERAL PUBLIC LICENSE' },
]
const server: Package[] = [{ name: 'pymupdf', version: '1.28.2', license: 'GNU AFFERO GPL 3.0', home: 'https://github.com/pymupdf/pymupdf' }]

const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })

beforeAll(async () => {
  await i18n.changeLanguage('en')
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/licenses.json') return json({ packages: browser })
    if (url === '/api/licenses') return json(server)
    return json({})
  }))
})
afterEach(() => {
  cleanup()
  vi.unstubAllEnvs()
})

function at(path: string, element: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{element}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('footer', () => {
  it('offers the source code and the licenses', () => {
    vi.stubEnv('VITE_SOURCE_URL', 'https://example.org/cbv')
    at('/', <Footer />)
    expect(screen.getByRole('link', { name: 'Source code' }).getAttribute('href')).toBe('https://example.org/cbv')
    expect(screen.getByRole('link', { name: 'Licenses' }).getAttribute('href')).toBe('/licenses')
  })

  it('stays out of the reader, which fills the screen', () => {
    at('/books/abc', <Footer />)
    expect(screen.queryByRole('link', { name: 'Licenses' })).toBeNull()
  })
})

describe('licenses page', () => {
  it("links the engine's exact source and lists every library with its license", async () => {
    at('/licenses', <Licenses />)
    await screen.findByRole('link', { name: 'chess.js' })
    const engine = screen.getByRole('link', { name: 'Stockfish.js source code' })
    expect(engine.getAttribute('href')).toBe('https://github.com/nmrugg/stockfish.js/tree/v19.0.1')
    expect(screen.getByRole('link', { name: 'License text' }).getAttribute('href')).toBe('/engine/Copying.txt')
    expect(await screen.findByText('pymupdf')).toBeTruthy()
    expect(screen.getByText('Copyright (c) 2025, Jeff Hlywa')).toBeTruthy()
  })

  it('without a published source, says the copy is your own', () => {
    vi.stubEnv('VITE_SOURCE_URL', '')
    at('/licenses', <Licenses />)
    expect(screen.getByText(/your own copy/)).toBeTruthy()
  })
})
