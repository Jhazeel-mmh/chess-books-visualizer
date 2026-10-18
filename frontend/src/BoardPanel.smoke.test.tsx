// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Diagram, Game, MoveNode } from './api'
import { BoardPanel } from './components/BoardPanel'
import i18n from './i18n'

// The board itself needs a real layout to animate; here it just shows its position.
vi.mock('./components/Board', () => ({ Board: ({ fen }: { fen: string }) => <div data-testid="board">{fen}</div> }))

// A stand-in for Stockfish: from any position it suggests 1.e4 e5 2.Nf3 (as far as that is legal).
vi.mock('./engine', async (original) => {
  const real = await original<typeof import('./engine')>()
  const lines = [{ depth: 18, score: { cp: 35 }, pv: ['e2e4', 'e7e5', 'g1f3'] }]
  return {
    ...real,
    engine: {
      analyse: async (_fen: string, options: { onUpdate?: (l: typeof lines) => void }) => {
        options.onUpdate?.(lines)
        return lines
      },
      stop: () => {},
    },
  }
})

const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
const root: MoveNode = { id: 'r', parent: null, children: [], san: null, uci: null, fen: START, nags: [], mainline: true, refs: [] }
const game: Game = { id: 'g1', title: 'A game', start_fen: START, root: 'r', nodes: [root] } as Game
const pawns = { id: 'd1', block: 0, key: 'k', label: null, placement: '8/pp3ppp/2p5/3p4/3P4/8/PP3PPP/8', turn: 'w', confidence: 1, uncertain: [], node: null } as unknown as Diagram

function panel(diagram?: Diagram) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <BoardPanel bookId="b" games={[game]} game={game} byId={new Map([['r', root]])} node={root} diagram={diagram} shown={diagram}
        onSelectGame={() => {}} onSelect={() => {}} onStep={() => {}} onExploreKeys={() => {}} />
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('en')
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })))
})
afterEach(cleanup)

describe('exploring on the reading board', () => {
  it('plays by the rules in a legal position', () => {
    panel()
    fireEvent.click(screen.getByText('Explore'))
    expect(screen.getByText(/drag a piece/)).toBeTruthy()
    fireEvent.click(screen.getByText('Back to the book'))
    expect(screen.queryByText(/drag a piece/)).toBeNull()
  })

  it('moves freely on a pawn structure', () => {
    panel(pawns)
    fireEvent.click(screen.getByText('Explore'))
    expect(screen.getByText(/pieces move anywhere/)).toBeTruthy()
  })
})

describe('the engine while reading', () => {
  it('opens from the button under the board or with E, and says when a position cannot be analysed', () => {
    panel(pawns)
    const button = screen.getByText('Engine')
    expect(button.getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(button)
    expect(button.getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByText(/can't analyse this position/)).toBeTruthy() // a pawn structure, no kings
    fireEvent.keyDown(window, { key: 'e' })
    expect(button.getAttribute('aria-pressed')).toBe('false')
    expect(screen.queryByText(/can't analyse this position/)).toBeNull()
  })
})

describe("the engine's line", () => {
  it('is numbered, in the reader\'s language, and plays on the board when clicked', async () => {
    await i18n.changeLanguage('es')
    panel()
    fireEvent.click(screen.getByText('Motor'))
    const nf3 = await screen.findByText('Cf3') // Spanish letters
    expect(screen.getAllByText('1.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('2.').length).toBeGreaterThan(0)
    fireEvent.click(nf3)
    // Played into Explore: the moves are listed there (numbered too), with a way back to the book.
    expect(await screen.findByText('Volver al libro')).toBeTruthy()
    expect(screen.getAllByText('e4').length).toBeGreaterThan(0)
    expect(screen.getByTestId('board').textContent).toBe('rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2')
    fireEvent.click(screen.getByText('Motor'))
    await i18n.changeLanguage('en')
  })
})
