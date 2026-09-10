import js from '@eslint/js';
import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
  js.configs.recommended,
  ...nextVitals,
  ...nextTs,
  {
    ignores: ['.next/**', '.next-phone/**', '.next-mobile/**', '.next-alpha-e2e/**', '.next-e2e/**', 'node_modules/**', 'out/**', 'next-env.d.ts']
  }
];

export default config;
