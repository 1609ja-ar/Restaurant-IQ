import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev proxy forwards /api to the FastAPI backend on 127.0.0.1:8010 (port 8000 may be
// blocked on some Windows machines). No request-body size limit is configured here.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8010", changeOrigin: true, timeout: 0, proxyTimeout: 0 },
    },
  },
  preview: {
    proxy: { "/api": { target: "http://127.0.0.1:8010", changeOrigin: true } },
  },
  build: { chunkSizeWarningLimit: 1200 },
  test: { environment: "node" },
} as never);
