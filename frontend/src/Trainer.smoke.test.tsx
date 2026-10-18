// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { SessionPlan, TrainerBook, TrainerRecord } from './api'
import i18n from './i18n'
import { Trainer } from './pages/Trainer'

const START = '6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1'
let record: TrainerRecord = {
  settings: { minutes: 50, rating: 1800, focus: null }, level: null, roles: {}, positions: {},
  reading: { book: null, at: {} }, games: { current: null, at: {} }, sources: {}, sessions: [], current: null,
}
const books: TrainerBook[] = [
  {
    id: 'b1', title: 'Deadly Checkmates', kind: 'pdf', role: 'tactics',
    material: { calculation: 800, endgame: 80, reading: 300, guess: 0 },
    uses: { calculation: true, endgame: false, reading: false, guess: false },
  },
  {
    id: 'b2', title: 'My System', kind: 'pdf', role: 'concepts',
    material: { calculation: 13, endgame: 19, reading: 235, guess: 4 },
    uses: { calculation: false, endgame: false, reading: true, guess: true },
  },
]
const plan: SessionPlan = {
  id: 's1', test: false, level: 3, planned: 20,
  blocks: [{
    kind: 'calculation', minutes: 20, items: [{
      book: 'b1', bookTitle: 'Deadly Checkmates', key: 'k1', diagram: 'd1', label: '7', fen: START, root: 'r', difficulty: 1,
      tree: [
        { id: 'r', parent: null, children: ['a'], san: null, uci: null, fen: START, nags: [], mainline: true },
        { id: 'a', parent: 'r', children: [], san: 'Rd8#', uci: 'd1d8', fen: '3R2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 1 1', nags: [], mainline: true },
      ],
    }],
  }],
}

const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })

beforeAll(async () => {
  await i18n.changeLanguage('en')
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (url === '/api/trainer' && init?.method === 'PUT') {
      record = JSON.parse(String(init.body))
      return new Response(null, { status: 204 })
    }
    if (url === '/api/trainer') return json(record)
    if (url === '/api/trainer/books') return json(books)
    if (url.startsWith('/api/trainer/session')) return json(plan)
    return json({})
  }))
})
afterEach(cleanup)

function renderTrainer() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Trainer />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('the trainer', () => {
  it('offers a session, a test, and the books with their roles', async () => {
    renderTrainer()
    expect(await screen.findByText('Start a 50-minute session')).toBeTruthy()
    expect(screen.getByText('Test: 6 positions in 45 min')).toBeTruthy()
    expect(await screen.findByText('Deadly Checkmates')).toBeTruthy()
    expect(screen.getByText('0 days in a row')).toBeTruthy()
    expect(screen.getByText('Books for each subject')).toBeTruthy()
  })

  it('lets you pick the books for each subject', async () => {
    renderTrainer()
    const box = await screen.findByLabelText('Calculation: My System')
    expect((box as HTMLInputElement).checked).toBe(false)
    expect((screen.getByLabelText('Calculation: Deadly Checkmates') as HTMLInputElement).checked).toBe(true)
    expect(screen.queryByLabelText('Guess the move: Deadly Checkmates')).toBeNull() // it has no games
    fireEvent.click(box)
    await screen.findAllByText('Back to automatic')
    expect(record.sources.calculation).toEqual(['b1', 'b2'])
    fireEvent.click(screen.getByText('Back to automatic'))
    await screen.findAllByText('automatic')
    expect(record.sources.calculation).toBeUndefined()
  })

  it('cancels a session only after asking', async () => {
    const before = record.sessions.length
    renderTrainer()
    fireEvent.click(await screen.findByText('Start a 50-minute session'))
    expect(await screen.findByText('White to play')).toBeTruthy()

    fireEvent.click(screen.getByText('Cancel session'))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText('Cancel this session?')).toBeTruthy()
    expect(document.activeElement?.textContent).toBe('No, keep training') // keeping it is the default
    fireEvent.click(within(dialog).getByText('No, keep training'))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(screen.getByText('White to play')).toBeTruthy()

    fireEvent.click(screen.getByText('Cancel session'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('alertdialog')).toBeNull()

    fireEvent.click(screen.getByText('Cancel session'))
    fireEvent.click(within(screen.getByRole('alertdialog')).getByText('Yes, cancel the session'))
    expect(await screen.findByText('Start a 50-minute session')).toBeTruthy()
    expect(record.current).toBeNull()
    expect(record.sessions).toHaveLength(before)
  })

  it('runs a calculation test and shows the book line after handing in', async () => {
    renderTrainer()
    fireEvent.click(await screen.findByText('Start a 50-minute session'))
    expect(await screen.findByText('White to play')).toBeTruthy()
    expect(screen.queryByText('Deadly Checkmates')).toBeNull() // the source stays hidden while solving
    fireEvent.click(screen.getByText('Hand in my line'))
    expect(await screen.findByText('Not solved')).toBeTruthy()
    expect(screen.getByText('1.Rd8#')).toBeTruthy()
    fireEvent.click(screen.getByText('Next'))
    expect(await screen.findByText('Session done')).toBeTruthy()
    fireEvent.click(screen.getByText('Save the session'))
    expect(await screen.findByText('Start a 50-minute session')).toBeTruthy()
    expect(record.sessions).toHaveLength(1)
    expect(record.positions['b1:k1'][0].result).toBe('wrong')
  })
})
