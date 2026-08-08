import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/" : "/",
  build: {
    outDir: "../src/retail_analytics_agent/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/health": "http://127.0.0.1:8005",
      "/ready": "http://127.0.0.1:8005",
      "/session": "http://127.0.0.1:8005",
      "/demo": "http://127.0.0.1:8005",
      "/auth": "http://127.0.0.1:8005",
      "/analysis": "http://127.0.0.1:8005",
      "/analytics": "http://127.0.0.1:8005",
      "/admin": "http://127.0.0.1:8005"
    }
  }
}));
