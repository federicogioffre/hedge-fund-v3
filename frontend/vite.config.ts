import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy target resolution, in order:
//   1. $VITE_API_URL  (set by run_windows.ps1 or docker-compose)
//   2. http://api:8000  (the Docker compose service name)
// In native Windows dev we set VITE_API_URL=http://localhost:8010 so
// the browser only talks to :5173 and Vite forwards /api/* to FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_URL || "http://api:8000",
        changeOrigin: true,
      },
    },
  },
});
