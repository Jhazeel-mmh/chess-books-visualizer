// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { Analysis, MoveNode } from './api'
import i18n from './i18n'
import Solver from './pages/Solver'

const START = '6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1'
const node = (id: string, parent: string | null, children: string[], san: string | null, uci: string | null, fen: string): MoveNode =>
  ({ id, parent, children, san, uci, fen, nags: [], mainline: true, refs: [] })

/** A book with one mate-in-one problem (number 7) and one game of 14 moves. */
function analysis(): Analysis {
  const gameMoves = ['e2e4', 'e7e5', 'g1f3', 'b8c6', 'f1b5', 'a7a6', 'b5a4', 'g8f6', 'e1g1', 'f8e7', 'f1e1', 'b7b5', 'a4b3', 'd7d6']
  const gameNodes: MoveNode[] = [node('g2r', null, ['m0'], null, null, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')]
  gameMoves.forEach((uci, i) => {
    gameNodes[gameNodes.length - 1].children = [`m${i}`]
    gameNodes.push(node(`m${i}`, i ? `m${i - 1}` : 'g2r', [], uci, uci, 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'))
  })
  return {
    notation: { lang: 'en', glyphs: {} },
    style: 'paragraph',
    unresolved: [],
    stats: { moves_found: 1, moves_resolved: 1, games: 2 },
    games: [
      { id: 'g1', title: null, start_fen: START, root: 'r', nodes: [node('r', null, ['a'], null, null, START), node('a', 'r', [], 'Rd8#', 'd1d8', '3R2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 1 1')] },
      { id: 'g2', title: 'Smith – Jones', start_fen: gameNodes[0].fen, root: 'g2r', nodes: gameNodes },
    ],
    diagrams: [
      { id: 'd0', block: 0, key: 'p1:10,10', label: '7', placement: START.split(' ')[0], turn: 'w', confidence: 1, uncertain: [], node: 'r', problem: true, solution: 'r', points: 2, section: null },
    ],
  } as unknown as Analysis
}

function renderSolver() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <Solver bookId="b" analysis={analysis()} onOpenInBook={() => {}} />
    </QueryClientProvider>,
  )
}

beforeAll(async () => {
  await i18n.changeLanguage('en')
  globalThis.ResizeObserver ??= class { observe() {} unobserve() {} disconnect() {} } as unknown as typeof ResizeObserver
  vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })))
})
afterEach(cleanup)

describe('solving mode', () => {
  it('shows the problem with its task and points', () => {
    renderSolver()
    expect(screen.getByText('Problem 7')).toBeTruthy()
    expect(screen.getByText('White to play')).toBeTruthy()
    expect(screen.getByText('2 points')).toBeTruthy()
    expect(screen.getByText('Hint')).toBeTruthy()
  })

  it('opens the games for guess-the-move', () => {
    renderSolver()
    fireEvent.click(screen.getByText('1 game'))
    expect(screen.getByText('Play White')).toBeTruthy()
    expect(screen.getByText('Smith – Jones')).toBeTruthy()
  })
})
