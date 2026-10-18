import type { Game } from './api'

/** Games long enough to guess their moves: a main line of at least this many moves (plies). */
const MIN_PLIES = 12

/** The book's games worth playing through in guess-the-move, titled ones first. */
export function longGames(games: Game[]): Game[] {
  const length = (g: Game) => {
    const byId = new Map(g.nodes.map((n) => [n.id, n]))
    let n = byId.get(g.root)
    let plies = 0
    while (n?.children.length) {
      n = byId.get(n.children[0])
      plies++
    }
    return plies
  }
  return games.filter((g) => length(g) >= MIN_PLIES).sort((a, b) => Number(!a.title) - Number(!b.title))
}
