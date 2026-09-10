/** @type {import('next').NextConfig} */
const isMobilePreview = process.env.HANDWRITE_MOBILE_PREVIEW === '1';
const isPhonePreview = process.env.HANDWRITE_PHONE_PREVIEW === '1';
const isAlphaE2E = process.env.HANDWRITE_ALPHA_E2E === '1';
const isStandardE2E = process.env.HANDWRITE_E2E === '1';

function distDir() {
  if (isMobilePreview) return '.next-mobile';
  if (isPhonePreview) return '.next-phone';
  if (isAlphaE2E) return '.next-alpha-e2e';
  if (isStandardE2E) return '.next-e2e';
  return '.next';
}

const nextConfig = {
  output: isMobilePreview ? undefined : 'standalone',
  // Preview/E2E runs beside the localhost studio without sharing Next's dev lock/cache.
  distDir: distDir(),
  async redirects() {
    return isMobilePreview
      ? [{ source: '/', destination: '/mobile', permanent: false }] : [];
  },
  ...(isPhonePreview && process.env.SITE_URL
    ? { allowedDevOrigins: [new URL(process.env.SITE_URL).hostname] } : {})
};

export default nextConfig;
