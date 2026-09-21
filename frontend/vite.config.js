import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_BASE is empty in dev so requests go through this proxy (no CORS),
// and is set to the deployed API origin in production builds.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": { target: process.env.VITE_PROXY_TARGET || "http://localhost:8000", changeOrigin: true },
      "/health": { target: process.env.VITE_PROXY_TARGET || "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 900 },
});
