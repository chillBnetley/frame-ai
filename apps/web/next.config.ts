import type { NextConfig } from "next";

const apiInternalUrl = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // An isolated E2E dev server must not reuse the interactive server's cache
  // or its single-instance lock.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  cacheComponents: true,
  partialPrefetching: true,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  experimental: {
    // The backend enforces the real 20 MiB limit; the dev proxy must not
    // truncate uploads before FastAPI can validate and answer.
    proxyClientMaxBodySize: "22mb",
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${apiInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
