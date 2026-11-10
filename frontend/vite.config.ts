import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig(({ mode }) => ({
  base: mode === "production" ? "/ui/" : "/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "build",
    assetsDir: "static",
    sourcemap: mode !== "production",
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (/node_modules\/(react|react-dom|react-router-dom)\//.test(id)) return "react-vendor";
          if (id.includes("node_modules/@radix-ui/")) return "ui-vendor";
          if (id.includes("node_modules/recharts/")) return "chart-vendor";
          if (id.includes("node_modules/d3/")) return "d3-vendor";
          if (/node_modules\/(react-hook-form|zod|@hookform)\//.test(id)) return "form-vendor";
        },
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/setupTests.ts",
    exclude: ["**/node_modules/**", "**/e2e/**", "**/dist/**", "**/build/**"],
  },
}));
