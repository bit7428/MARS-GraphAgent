import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/runs": { target: backend, changeOrigin: false },
      "/graph": { target: backend, changeOrigin: false },
      "/config": { target: backend, changeOrigin: false },
      "/health": { target: backend, changeOrigin: false },
      "/meta": { target: backend, changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
