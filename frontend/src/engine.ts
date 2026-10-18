/**
 * The local chess engine: Stockfish (WASM, single-threaded "lite" build) in a Web Worker.
 *
 * Everything runs in the browser, offline. The engine starts the first time it is asked for
 * something. One search runs at a time; asking again stops the search in progress, which then
 * answers with what it had found so far.
 */

/** A score from the point of view of the side to move: centipawns, or mate in N (negative: being mated). */
export interface Score {
  cp?: number
  mate?: number
}

export interface EngineLine {
  depth: number
  score: Score
  /** Best moves in UCI ("e2e4", "e7e8q"). */
  pv: string[]
}

export interface AnalyseOptions {
  movetime?: number
  depth?: number
  /** How many different best moves to report. */
  multipv?: number
  /** Called with the lines found so far, as the search deepens. */
  onUpdate?: (lines: EngineLine[]) => void
}

const ENGINE_URL = '/engine/stockfish-19-lite-single.js'

/** Parses a UCI "info" line; null for lines without a scored principal variation. */
export function parseInfo(line: string): (EngineLine & { multipv: number }) | null {
  if (!line.startsWith('info ') || !line.includes(' pv ')) return null
  const depth = /\bdepth (\d+)/.exec(line)
  const multipv = /\bmultipv (\d+)/.exec(line)
  const score = /\bscore (cp|mate) (-?\d+)/.exec(line)
  const pv = / pv (.+)$/.exec(line)
  if (!depth || !score || !pv) return null
  if (/\b(lowerbound|upperbound)\b/.test(line)) return null
  return {
    depth: Number(depth[1]),
    multipv: multipv ? Number(multipv[1]) : 1,
    score: score[1] === 'cp' ? { cp: Number(score[2]) } : { mate: Number(score[2]) },
    pv: pv[1].trim().split(/\s+/),
  }
}

/** A score as centipawns for comparing (mates count as ±100000, quicker mates more). */
export function scoreValue(score: Score): number {
  if (score.mate === undefined) return score.cp ?? 0
  if (score.mate === 0) return -100000
  return score.mate > 0 ? 100000 - score.mate : -100000 - score.mate
}

/** "+1.3", "−0.4", "#3", "−#2". */
export function formatScore(score: Score): string {
  if (score.mate !== undefined) return score.mate >= 0 ? `#${score.mate}` : `−#${-score.mate}`
  const pawns = (score.cp ?? 0) / 100
  return `${pawns > 0 ? '+' : pawns < 0 ? '−' : ''}${Math.abs(pawns).toFixed(1)}`
}

/** The score seen from the other side. */
export function flip(score: Score): Score {
  return score.mate !== undefined ? { mate: -score.mate } : { cp: -(score.cp ?? 0) }
}

interface Search {
  lines: Map<number, EngineLine>
  options: AnalyseOptions
  resolve: (lines: EngineLine[]) => void
}

class Engine {
  private worker: Worker | null = null
  private started: Promise<void> | null = null
  private waiting: ((line: string) => boolean) | null = null
  private search: Search | null = null
  private next: { fen: string; options: AnalyseOptions; resolve: (lines: EngineLine[]) => void } | null = null

  private start(): Promise<void> {
    if (!this.started) {
      this.started = new Promise((resolve, reject) => {
        try {
          this.worker = new Worker(ENGINE_URL)
        } catch (e) {
          reject(e)
          return
        }
        this.worker.onmessage = (e: MessageEvent) => this.onLine(String(e.data))
        this.worker.onerror = (e) => reject(e)
        this.expect('uciok', () => {
          this.send('isready')
          this.expect('readyok', resolve)
        })
        this.send('uci')
      })
    }
    return this.started
  }

  private send(command: string) {
    this.worker?.postMessage(command)
  }

  private expect(word: string, then: () => void) {
    this.waiting = (line) => {
      if (line !== word) return false
      this.waiting = null
      then()
      return true
    }
  }

  private onLine(line: string) {
    if (this.waiting?.(line)) return
    const search = this.search
    if (!search) return
    const info = parseInfo(line)
    if (info) {
      search.lines.set(info.multipv, info)
      search.options.onUpdate?.(this.sorted(search))
    } else if (line.startsWith('bestmove')) {
      this.search = null
      search.resolve(this.sorted(search))
      this.run()
    }
  }

  private sorted(search: Search): EngineLine[] {
    return [...search.lines.entries()].sort(([a], [b]) => a - b).map(([, l]) => l)
  }

  /** Searches a position (FEN); a newer request stops this one, which then resolves early. */
  async analyse(fen: string, options: AnalyseOptions = {}): Promise<EngineLine[]> {
    await this.start()
    return new Promise((resolve) => {
      this.next?.resolve([])
      this.next = { fen, options, resolve }
      if (this.search) this.send('stop')
      else this.run()
    })
  }

  /** Stops whatever the engine is doing. */
  stop() {
    this.next?.resolve([])
    this.next = null
    if (this.search) this.send('stop')
  }

  private run() {
    const job = this.next
    if (!job) return
    this.next = null
    this.search = { lines: new Map(), options: job.options, resolve: job.resolve }
    this.send(`setoption name MultiPV value ${job.options.multipv ?? 1}`)
    this.send(`position fen ${job.fen}`)
    this.send(job.options.depth ? `go depth ${job.options.depth}` : `go movetime ${job.options.movetime ?? 1000}`)
  }
}

export const engine = new Engine()
