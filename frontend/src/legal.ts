/**
 * Where this app's source code is published, set at build time. The app is AGPL: everyone who
 * uses it, also over the internet, must be offered its source.
 */
export function sourceUrl(): string | undefined {
  return import.meta.env.VITE_SOURCE_URL || undefined
}
