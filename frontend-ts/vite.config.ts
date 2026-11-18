import { defineConfig } from "vite";
import type { ProxyOptions } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /backend/<port>/... (REST + WebSocket) to 127.0.0.1:<port>,
// mirroring frontend/serve.py, because the backend has no CORS support.
const proxy: Record<string, ProxyOptions> = {};
for (const port of [8000, 8001, 8002, 8003]) {
  proxy[`^/backend/${port}/`] = {
    target: `http://127.0.0.1:${port}`,
    ws: true,
    changeOrigin: true,
    rewrite: (path) => path.replace(/^\/backend\/\d+/, ""),
  };
}

export default defineConfig({
  plugins: [react()],
  server: { port: 3000, proxy },
});
