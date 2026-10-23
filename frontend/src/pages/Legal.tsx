import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Package } from '../api'
import { Markdown } from '../components/Markdown'
import { sourceUrl } from '../legal'
import { POLICIES, policyValues, type PolicyName } from '../policy'

const AGPL = 'https://www.gnu.org/licenses/agpl-3.0.html'
const STOCKFISH = 'https://github.com/official-stockfish/Stockfish'
const PIECES = 'https://commons.wikimedia.org/wiki/Category:SVG_chess_pieces'

/** This app's license and source, and those of everything it is built from. */
export function Licenses() {
  const { t } = useTranslation()
  const browser = useQuery({ queryKey: ['licenses', 'browser'], queryFn: api.browserLicenses, staleTime: Infinity })
  const server = useQuery({ queryKey: ['licenses', 'server'], queryFn: api.serverLicenses, staleTime: Infinity })
  const source = sourceUrl()
  // The engine is sent to every browser, so its exact source must be reachable from here.
  const stockfish = browser.data?.find((p) => p.name === 'stockfish')
  const engineSource = stockfish?.repository ? `${stockfish.repository}/tree/v${stockfish.version}` : 'https://github.com/nmrugg/stockfish.js'
  return (
    <main className="legal">
      <h1>{t('legal.licenses.title')}</h1>
      <section>
        <h2>{t('legal.licenses.app')}</h2>
        <p>{t('legal.licenses.appText')}</p>
        <p className="legal-links">
          {source ? <a href={source}>{t('legal.sourceCode')}</a> : <span>{t('legal.licenses.ownCopy')}</span>}
          <a href={AGPL}>{t('legal.licenses.agpl')}</a>
        </p>
      </section>
      <section>
        <h2>{t('legal.licenses.engine')}</h2>
        <p>{t('legal.licenses.engineText', { version: stockfish ? ` ${stockfish.version}` : '' })}</p>
        <p className="legal-links">
          <a href={engineSource}>{t('legal.licenses.engineSource')}</a>
          <a href={STOCKFISH}>{t('legal.licenses.stockfishSource')}</a>
          <a href="/engine/Copying.txt">{t('legal.licenses.engineLicense')}</a>
        </p>
      </section>
      <section>
        <h2>{t('legal.licenses.pieces')}</h2>
        <p>{t('legal.licenses.piecesText')} <a href={PIECES}>Wikimedia Commons</a></p>
      </section>
      <section>
        <h2>{t('legal.licenses.browser')}</h2>
        <Packages packages={browser.data} failed={browser.isError} />
      </section>
      <section>
        <h2>{t('legal.licenses.server')}</h2>
        <Packages packages={server.data} failed={server.isError} />
      </section>
    </main>
  )
}

function Packages({ packages, failed }: { packages?: Package[]; failed: boolean }) {
  const { t } = useTranslation()
  if (failed) return <p className="notice">{t('legal.licenses.unavailable')}</p>
  if (!packages) return <p className="notice">…</p>
  return (
    <ul className="packages">
      {packages.map((p) => {
        const where = p.repository ?? p.home
        const name = where ? <a href={where}>{p.name}</a> : p.name
        const label = <>{name} {p.version} <span className="hint">{p.license ?? '?'}</span></>
        return (
          <li key={p.name}>
            {p.text ? <details><summary>{label}</summary><pre>{p.text}</pre></details> : label}
          </li>
        )
      })}
    </ul>
  )
}

/** One of a hosted site's legal texts (see policy.tsx), in the reader's language, its blanks filled with the site's settings. */
export function Policy({ name }: { name: PolicyName }) {
  const { i18n } = useTranslation()
  const lang = i18n.resolvedLanguage === 'en' ? 'en' : 'es'
  const text = useQuery({ queryKey: ['policy', name, lang], queryFn: POLICIES[`./policies/${name}.${lang}.md`], staleTime: Infinity })
  const legal = useQuery({ queryKey: ['legal'], queryFn: api.legal, staleTime: Infinity })
  if (!text.data || legal.isPending) return <p className="notice">…</p>
  return (
    <main className="policy">
      <Markdown text={text.data} values={policyValues(legal.data)} />
    </main>
  )
}
