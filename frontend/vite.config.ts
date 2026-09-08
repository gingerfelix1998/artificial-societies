import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Localhost only. This UI talks to an API with no authentication that serves
// analyst-facing data, so neither half is bound to a public interface.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      // In development the API runs separately on 8000 (`make api`). In the demo build
      // it serves this bundle itself, so the same relative paths work either way.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Progress is server-sent events; buffering the proxy would defeat the point of
        // streaming a distribution as it lands.
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
            }
          })
        },
      },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
})
