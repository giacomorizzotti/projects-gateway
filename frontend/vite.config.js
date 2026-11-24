import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// mini's SCSS: mini is checked out next to this repository (../mini), as src/mini's symlink
// expects; the Docker build puts it at the same place relative to the app. MINI_CSS_DIR overrides.
const miniCssDir = process.env.MINI_CSS_DIR || fileURLToPath(new URL('../../mini/css/', import.meta.url))

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5180,
    strictPort: true,          // the auth server only accepts http://localhost:5180/callback
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010' },
    },
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    // src/mini is a symlink to mini_vue: keep its imports resolving from this project.
    preserveSymlinks: true,
  },
  css: {
    preprocessorOptions: {
      scss: { loadPaths: [miniCssDir] },
    },
  },
})
