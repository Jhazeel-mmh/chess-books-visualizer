// Copies the Stockfish engine (WASM, single-threaded "lite" build) next to the app's static files,
// so it is served locally and works offline. Runs after install and before dev/build.
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const require = createRequire(import.meta.url)
const source = join(dirname(require.resolve('stockfish/package.json')), 'bin')
const target = join(dirname(fileURLToPath(import.meta.url)), '..', 'public', 'engine')
mkdirSync(target, { recursive: true })
for (const file of ['stockfish-19-lite-single.js', 'stockfish-19-lite-single.wasm']) {
  if (!existsSync(join(target, file))) copyFileSync(join(source, file), join(target, file))
}
