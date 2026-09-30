/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The API allows this exact origin via CORS_ORIGINS (http://localhost:5173).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  test: { environment: "node" },
});
