import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('.', import.meta.url))
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './test/setup.ts',
    exclude: ['.next/**', '.next-phone/**', '.next-mobile/**', '.next-alpha-e2e/**', '.next-e2e/**', 'e2e/**', 'e2e-alpha/**', 'e2e-mobile/**', 'node_modules/**']
  }
});
