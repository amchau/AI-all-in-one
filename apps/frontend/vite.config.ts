import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "claims-api-proxy-allowlist",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          const pathname = (request.url ?? "").split("?")[0];
          if (
            pathname === "/api"
            || (
              pathname.startsWith("/api/")
              && pathname !== "/api/v1/claims/hybrid-investigations"
              && pathname !== "/api/v1/claims/workflows"
              && !pathname.startsWith("/api/v1/claims/workflows/")
            )
          ) {
            response.statusCode = 404;
            response.end();
            return;
          }
          next();
        });
      },
    },
  ],
  server: {
    proxy: {
      "/api/v1/claims/hybrid-investigations": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.split("?")[0].replace(/^\/api/, ""),
      },
      "/api/v1/claims/workflows": {
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.split("?")[0].replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    restoreMocks: true,
    clearMocks: true,
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/api.ts", "src/validation.ts", "src/App.tsx"],
      thresholds: { lines: 80, functions: 80, branches: 80, statements: 80 },
    },
  },
});