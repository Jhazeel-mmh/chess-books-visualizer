import type { ReactNode } from 'react'
import type { Legal } from './api'

// A hosted site's terms of use, privacy notice and copyright policy (src/policies), shown by
// pages/Legal.tsx. Written in Spanish (the version that prevails) and translated to English: drafts
// for a lawyer to review before the site opens.

export type PolicyName = 'terms' | 'privacy' | 'copyright'

export const POLICIES = import.meta.glob<string>('./policies/*.md', { query: '?raw', import: 'default' })

/** What each {blank} of the texts says. A setting the server lacks shows its name, to be filled in. */
export function policyValues(legal: Legal | undefined): Record<string, ReactNode> {
  const unset = (setting: string) => <span className="unset">[{setting}]</span>
  const text = (value: string | null | undefined, setting: string) => value || unset(setting)
  const email = (value: string | null | undefined, setting: string) => (value ? <a href={`mailto:${value}`}>{value}</a> : unset(setting))
  const site = legal?.site
  return {
    site: site ? <a href={site}>{site.replace(/^https?:\/\//, '')}</a> : unset('CBV_PUBLIC_URL'),
    operator: text(legal?.operator, 'CBV_OPERATOR'),
    address: text(legal?.address, 'CBV_OPERATOR_ADDRESS'),
    contact: email(legal?.contact, 'CBV_CONTACT_EMAIL'),
    copyrightEmail: email(legal?.copyright_email, 'CBV_COPYRIGHT_EMAIL'),
    copyrightAgent: text(legal?.copyright_agent, 'CBV_COPYRIGHT_AGENT'),
    strikes: legal?.strikes ?? '…',
    keepDays: legal?.keep_days ?? '…',
    waitDays: legal?.wait_days ?? '…',
    sessionDays: legal?.session_days ?? '…',
    unverifiedDays: legal?.unverified_days ?? '…',
    renderDays: legal?.render_days ?? '…',
  }
}
