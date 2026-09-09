import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // Disable Vite's response buffering for SSE endpoints so log lines
        // reach the browser as they are emitted rather than all at once.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes, _req, res) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              // Flush headers immediately and pipe the response directly,
              // bypassing http-proxy's internal buffering.
              res.writeHead(proxyRes.statusCode ?? 200, {
                ...proxyRes.headers,
                "cache-control": "no-cache",
                "x-accel-buffering": "no",
              });
              proxyRes.pipe(res, { end: true });
            }
          });
        },
      },
    },
  },
});
