import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build lands inside the Python package so `scianim serve` ships the UI without Node at run time.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/scianim/server/static",
    emptyOutDir: true,
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8765" },
  },
});
