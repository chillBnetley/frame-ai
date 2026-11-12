import type { NextConfig } from "next";

const apiInternalUrl = (process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // The Windows package ships a traced server bundle instead of node_modules.
  output: process.env.NEXT_STANDALONE === "1" ? "standalone" : undefined,
  // Runtime data and secrets live outside the program directory. Tracing
  // follows the proxy's fs reads, so exclude those paths explicitly; the build
  // script also copies only the web subtree and re-checks the result.
  outputFileTracingExcludes: {
    "*": [
      "../../data/**",
      "../data/**",
      "data/**",
      "../../eval-data/**",
      "../eval-data/**",
      "../../.env",
      "../.env",
      ".env",
    ],
  },
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
