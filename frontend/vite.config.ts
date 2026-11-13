/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs on 8000; in compose nginx does this proxying (nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    // Above 15000, like the compose ports: Windows reserves random ranges below that.
    port: 25173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
  },
})
