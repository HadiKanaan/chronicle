import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 127.0.0.1, not "localhost": uvicorn binds IPv4, but on Windows "localhost"
      // resolves to IPv6 (::1) first and stalls ~2s per request before falling
      // back to IPv4. Hitting the IPv4 address directly removes that delay.
      '/api': 'http://127.0.0.1:8000'
    }
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});