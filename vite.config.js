import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import os from 'node:os';
import path from 'node:path';

// Project lives on an SMB network share (\\diskstation1621\...).
// On Windows, Vite's default realpath + exports resolution and esbuild's
// mmap-backed cache both misbehave over SMB. Two adjustments make it work:
//   - preserveSymlinks: skip the realpath step that maps to a UNC path
//   - cacheDir on local %TEMP%: keep Vite's dep cache off the share
export default defineConfig({
  plugins: [react()],
  resolve: {
    preserveSymlinks: true,
  },
  cacheDir: path.join(os.tmpdir(), 'vite-abc-sip-prototype'),
  server: {
    fs: {
      strict: false,
    },
  },
  build: {
    outDir: 'dist',
  },
});
