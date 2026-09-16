import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Every request to /api/... is forwarded to the Python backend, so the browser
// only ever talks to one origin and there are no CORS problems in development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://localhost:8000' },
  },
})
