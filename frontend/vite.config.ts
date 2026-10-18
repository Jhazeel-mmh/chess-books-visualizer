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
})
