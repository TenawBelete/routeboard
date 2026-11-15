import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000 (docker compose publishes it on 127.0.0.1).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000", "/health": "http://127.0.0.1:8000", "/live/": "http://127.0.0.1:8001" } },
});
