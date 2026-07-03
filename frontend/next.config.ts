import type { NextConfig } from "next";

const BACKEND_ORIGIN =
  process.env.LEADMINE_BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        // Same-origin proxy so httpOnly cookies flow to the FastAPI backend
        // and the browser never talks to :8000 cross-origin.
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
