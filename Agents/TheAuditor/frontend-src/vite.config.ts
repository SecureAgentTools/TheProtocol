import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': resolve(__dirname, 'src') } },
  build: {
    outDir: '../frontend',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          'chart-vendor': ['chart.js', 'vue-chartjs'],
        },
      },
    },
  },
  server: {
    port: 5175,
    proxy: {
      '/api': { target: 'http://localhost:8045', changeOrigin: true },
      '/ws': { target: 'ws://localhost:8045', ws: true },
    },
  },
})
