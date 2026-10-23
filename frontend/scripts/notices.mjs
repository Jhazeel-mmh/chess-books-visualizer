// Writes public/licenses.json: every package the browser code is built from (the production
// dependencies and theirs), with its license text. The bundle is minified, so this is how their
// copyright notices and licenses reach the people the code is sent to. Runs before dev/build.
import { existsSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import { dirname, join, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const LICENSE_FILE = /^(licen[cs]e|copying)([.-].*)?$/i

/** Where ``name`` is installed for the package in ``from`` (Node's lookup, through pnpm's links). */
function find(name, from) {
  for (let dir = from; ; dir = dirname(dir)) {
    if (basename(dir) !== 'node_modules') {
      const candidate = join(dir, 'node_modules', name)
      if (existsSync(join(candidate, 'package.json'))) return realpathSync(candidate)
    }
    if (dirname(dir) === dir) return null
  }
}

function repository(pkg) {
  const url = typeof pkg.repository === 'string' ? pkg.repository : pkg.repository?.url
  if (!url) return pkg.homepage ?? null
  return url
    .replace(/^git\+/, '')
    .replace(/^git:\/\//, 'https://')
    .replace(/^github:/, 'https://github.com/')
    .replace(/^([\w-]+\/[\w.-]+)$/, 'https://github.com/$1')
    .replace(/\.git$/, '')
}

const found = new Map()
const queue = [root]
while (queue.length) {
  const dir = queue.shift()
  const pkg = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'))
  if (dir !== root) {
    const key = `${pkg.name}@${pkg.version}`
    if (found.has(key)) continue
    const file = readdirSync(dir).find((f) => LICENSE_FILE.test(f))
    found.set(key, {
      name: pkg.name,
      version: pkg.version,
      license: pkg.license ?? pkg.licenses?.map((l) => l.type).join(' OR ') ?? null,
      repository: repository(pkg),
      text: file ? readFileSync(join(dir, file), 'utf8') : null,
    })
  }
  for (const name of Object.keys({ ...pkg.dependencies, ...pkg.optionalDependencies })) {
    const at = find(name, dir)
    if (at) queue.push(at)
  }
}

const packages = [...found.values()].sort((a, b) => a.name.localeCompare(b.name))
writeFileSync(join(root, 'public', 'licenses.json'), JSON.stringify({ packages }) + '\n')
