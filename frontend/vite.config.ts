import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Relative base so assets resolve under any mount prefix (standalone at "/",
// embedded under "/schedule-visualizer/"). Build lands in the Python package so
// the FastAPI app can serve it and the wheel can ship it.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../src/schedule_visualizer/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8888",
    },
  },
});
