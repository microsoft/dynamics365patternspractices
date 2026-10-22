import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { localRunnerPlugin } from './scripts/localRunnerPlugin.js'

const adoProxy = {
  '/ado-proxy': {
    target: 'https://dev.azure.com',
    changeOrigin: true,
    secure: true,
    rewrite: (path) => path.replace(/^\/ado-proxy/, ''),
  },
  // Extension Management API (DevLabs Multivalue install/check)
  '/extmgmt-proxy': {
    target: 'https://extmgmt.dev.azure.com',
    changeOrigin: true,
    secure: true,
    rewrite: (path) => path.replace(/^\/extmgmt-proxy/, ''),
  },
  '/api': {
    target: 'http://127.0.0.1:8787',
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/api/, ''),
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), localRunnerPlugin()],
  server: {
    open: true,
    proxy: adoProxy,
  },
  preview: {
    open: true,
    proxy: adoProxy,
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
})
