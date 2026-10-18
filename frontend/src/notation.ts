const LETTERS: Record<string, Record<string, string>> = {
  en: { K: 'K', Q: 'Q', R: 'R', B: 'B', N: 'N' },
  es: { K: 'R', Q: 'D', R: 'T', B: 'A', N: 'C' },
}
const FIGURINES: Record<string, string> = { K: '♔', Q: '♕', R: '♖', B: '♗', N: '♘' }

const NAG_SYMBOLS: Record<number, string> = {
  1: '!', 2: '?', 3: '!!', 4: '??', 5: '!?', 6: '?!', 7: '□', 10: '=', 13: '∞',
  14: '⩲', 15: '⩱', 16: '±', 17: '∓', 18: '+−', 19: '−+', 146: 'N',
}

/** SAN (always English letters from the backend) in the reader's language or as figurines. */
export function displaySan(san: string, lang: string, figurines: boolean): string {
  const map = figurines ? FIGURINES : (LETTERS[lang] ?? LETTERS.en)
  return san.replace(/[KQRBN]/g, (c) => map[c])
}

export function nagSymbols(nags: number[]): string {
  return nags.map((n) => NAG_SYMBOLS[n] ?? '').join('')
}

/** Move number and side for the move played from `fenBefore`. */
export function moveNumber(fenBefore: string): { number: number; white: boolean } {
  const fields = fenBefore.split(' ')
  return { number: Number(fields[5]), white: fields[1] === 'w' }
}

/** The number to print before each move of a line played from `fen`: "12." for White, "12…" for Black's first move, else "". */
export function lineNumbers(fen: string, count: number): string[] {
  const { number, white } = moveNumber(fen)
  return Array.from({ length: count }, (_, i) => {
    const whiteMove = white ? i % 2 === 0 : i % 2 === 1
    const n = number + Math.floor((i + (white ? 0 : 1)) / 2)
    return whiteMove ? `${n}.` : i === 0 ? `${n}…` : ''
  })
}
