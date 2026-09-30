/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development, Vite forwards API paths to uvicorn, so the page and the API
// share one origin (http://localhost:5173) and the session cookie just works.
const API = "http://127.0.0.1:8000";
const API_PATHS = ["/auth", "/chat", "/conversations", "/images", "/whoami", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: Object.fromEntries(API_PATHS.map((path) => [path, { target: API }])),
  },
  test: {
    environment: "node", // component tests opt into jsdom with a file comment
    coverage: {
      include: ["src/**"],
      exclude: ["src/**/*.test.*", "src/main.tsx"],
      reporter: ["text-summary", "text"],
    },
  },
});
