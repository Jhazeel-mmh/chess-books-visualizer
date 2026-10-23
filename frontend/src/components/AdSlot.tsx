import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { usePlan } from '../plan'

// An ad (Google AdSense) for a free account of a hosted site. Only pages that show nothing of a
// book have one: the library, and the trainer's start and summary (Plans.smoke.test.tsx checks
// where). Never the reader, the solver or a trainer block: AdSense allows no ads beside content
// the site has no rights to, and a site that earns from its users' books loses the protection the
// law gives a host.

const ADSENSE = 'https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'

declare global {
  interface Window {
    adsbygoogle?: object[]
  }
}

export function AdSlot() {
  const { t } = useTranslation()
  const ads = usePlan()?.ads
  // Each ad unit is filled once (React runs effects twice while developing).
  const filled = useRef(false)
  useEffect(() => {
    if (!ads || filled.current) return
    filled.current = true
    if (!document.querySelector(`script[src^="${ADSENSE}"]`)) {
      const script = document.createElement('script')
      script.async = true
      script.crossOrigin = 'anonymous'
      script.src = `${ADSENSE}?client=${encodeURIComponent(ads.client)}`
      document.head.appendChild(script)
    }
    ;(window.adsbygoogle ??= []).push({})
  }, [ads])
  if (!ads) return null
  return (
    <aside className="ad-slot">
      <span className="ad-label">{t('plans.ad')}</span>
      <ins className="adsbygoogle" style={{ display: 'block' }} data-ad-client={ads.client} data-ad-slot={ads.slot}
        data-ad-format="auto" data-full-width-responsive="true" />
    </aside>
  )
}
