import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone) for the Docker
  // runner image — no node_modules copy, just `node server.js`.
  output: "standalone",
  async rewrites() {
    // Read the backend URL at build time; defaults to localhost for dev.
    // In production, the LEADMINE_BACKEND_ORIGIN env var must be set
    // (e.g. via Docker ARG/ENV during the build stage).
    const backend = process.env.LEADMINE_BACKEND_ORIGIN ?? "http://localhost:8000";
    return [
      {
        // Same-origin proxy so httpOnly cookies flow to the FastAPI backend
        // and the browser never talks to :8000 cross-origin.
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
