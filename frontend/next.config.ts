import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  eslint: {
    // These warnings come from upstream LiveKit/AI UI components, not our code.
    ignoreDuringBuilds: true,
  },
  outputFileTracingIncludes: {
    // The header checks whether the configured logo exists in /public, and the
    // OpenGraph route reads its background and wordmark from disk. Serverless
    // bundles do not include public/ unless it is traced, so on Vercel or
    // Netlify the logo would silently fall back to text and the social card to
    // a gradient. public/ is ~330 KB, so tracing it is cheap.
    '/': ['./public/**'],
    '/opengraph-image': ['./public/**'],
  },
};

export default nextConfig;
