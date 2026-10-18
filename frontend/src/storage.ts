// Per-browser view settings (reading position, zoom…). Storage may be unavailable
// (private windows, blocked site data), so every access falls back quietly.

const PREFIX = 'cbv.'

export function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function save(key: string, value: unknown): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    // Not saved: the reader still works, it just won't remember.
  }
}
