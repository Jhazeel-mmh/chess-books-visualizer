import { describe, expect, it } from 'vitest'
import { blanks, blocks } from './markdown'
import { policyValues } from './policy'

// The legal texts: written in Spanish, translated to English. Both versions must say the same things.
const TEXTS = import.meta.glob<string>('./policies/*.md', { query: '?raw', import: 'default', eager: true })
const text = (name: string, lang: string) => TEXTS[`./policies/${name}.${lang}.md`]
const NAMES = ['terms', 'privacy', 'copyright']
// The pages of the app the texts may link to, and the sites outside it.
const PAGES = ['/terms', '/privacy', '/copyright/policy', '/copyright', '/licenses', '/account', '/plans']
const SITES = ['www.paddle.com', 'policies.google.com', 'www.google.com', 'www.aboutads.info']

const headings = (md: string, level: string) => blocks(md).filter((b) => b.kind === level)
const links = (md: string) => [...md.matchAll(/\]\(([^)]+)\)/g)].map((m) => m[1])
const sorted = (items: string[]) => [...new Set(items)].sort()

describe('the legal texts', () => {
  it('exist in both languages, and nothing else is there', () => {
    expect(Object.keys(TEXTS).sort()).toEqual(NAMES.flatMap((n) => [`./policies/${n}.en.md`, `./policies/${n}.es.md`]).sort())
  })

  it.each(NAMES)('%s: the translation has every section, blank and link of the Spanish', (name) => {
    const [es, en] = [text(name, 'es'), text(name, 'en')]
    expect(headings(en, 'h1')).toHaveLength(1)
    expect(headings(en, 'h2').length).toBe(headings(es, 'h2').length)
    // Sections are numbered alike.
    const numbers = (md: string) => headings(md, 'h2').map((h) => ('text' in h ? h.text.split(' ')[0] : ''))
    expect(numbers(en)).toEqual(numbers(es))
    expect(sorted(blanks(en))).toEqual(sorted(blanks(es)))
    expect(sorted(links(en))).toEqual(sorted(links(es)))
  })

  it.each(NAMES)('%s: every blank is filled and every link goes somewhere', (name) => {
    const known = Object.keys(policyValues(undefined))
    for (const lang of ['es', 'en']) {
      const md = text(name, lang)
      for (const blank of blanks(md)) expect(known).toContain(blank)
      for (const href of links(md)) {
        if (href.startsWith('/')) expect(PAGES).toContain(href)
        else expect(SITES).toContain(new URL(href).protocol === 'https:' && new URL(href).host)
      }
      expect(md).toMatch(lang === 'es' ? /Última actualización: \d+ de \w+ de 20\d\d\./ : /Last updated: \w+ \d+, 20\d\d\./)
    }
  })

  it('the English says the Spanish prevails', () => {
    for (const name of NAMES) expect(text(name, 'en')).toContain('the Spanish version, which prevails')
  })
})

describe('the Markdown they are written in', () => {
  it('has headings, paragraphs and lists', () => {
    const md = '# Title\n\nOne line\nand the next.\n\n- a\n- b\n  goes on\n\n1. first\n2. second\nAfter.'
    expect(blocks(md)).toEqual([
      { kind: 'h1', text: 'Title' },
      { kind: 'p', text: 'One line and the next.' },
      { kind: 'ul', items: ['a', 'b goes on'] },
      { kind: 'ol', items: ['first', 'second'] },
      { kind: 'p', text: 'After.' },
    ])
  })
})
