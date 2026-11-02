import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the Vite server proxies API, media streams and WebSocket
// traffic to the FastAPI backend on port 8000.
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/ws": { target: BACKEND.replace(/^http/, "ws"), ws: true },
    },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 1200 },
});
