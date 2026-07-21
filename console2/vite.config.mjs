import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { bundleBudgetPlugin, manualChunks } from './src/config/build.js'

export default defineConfig({
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
    },
    warmup: {
      clientFiles: ["./src/main.jsx"],
    },
  },
  plugins: [react(), bundleBudgetPlugin()],
  build: {
    chunkSizeWarningLimit: 750,
    rollupOptions: {
      output: { manualChunks },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.js"],
  },
});
