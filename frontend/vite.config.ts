import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Single origin, always. In prod FastAPI serves dist/ and the API from the same host, so the
// SPA only ever uses relative /api paths. In dev, this proxy reproduces that: /api -> the local
// FastAPI. That is why there is no CORS middleware in the backend and no VITE_API_BASE_URL here
// — if either ever appears, the single-origin invariant has been broken. See ../CLAUDE.md.
export default defineConfig({
  // Pinned explicitly rather than left to process.cwd(): on a Windows *mapped network drive*
  // (this repo lives on O: -> \\diskstation1621\AiExposedFolders) Vite resolves the root through
  // to the UNC path and then fails to load index.html. Irrelevant in Docker/CI (Linux, no
  // mapped drive) — this is purely so a local `npm run build` works on that setup.
  root: fileURLToPath(new URL(".", import.meta.url)),
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: false },
    },
  },
  // Windows mapped-network-drive workaround, and the reason is specific: this repo lives on
  // O: -> \\diskstation1621\AiExposedFolders, and fs.realpathSync.native() returns the UNC form
  // ("\\Diskstation1621\...") where plain realpathSync returns "O:\...". Vite uses .native, then
  // normalizes the leading \\ into "/Diskstation1621/...", which Node resolves against the current
  // drive -> ENOENT. preserveSymlinks skips the realpath step entirely.
  //
  // Harmless everywhere else (this project has no symlinked/monorepo deps), and irrelevant to
  // the Docker build, which runs on Linux with no drive mapping.
  resolve: { preserveSymlinks: true },
  build: {
    // FastAPI mounts this directory (backend/app/main.py). Keep it in step with that path.
    outDir: "dist",
    sourcemap: true,
  },
});
