/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    // The app is served from the reader's own computer, where a ~0.5 MB bundle loads at once.
    chunkSizeWarningLimit: 800,
  },
  test: {
    // Test files run side by side, and pages that load later (the legal texts, the trainer) can
    // take seconds on a busy machine: wait for them rather than fail.
    testTimeout: 15_000,
    setupFiles: ['src/test-setup.ts'],
  },
})
