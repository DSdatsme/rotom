import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Pin the workspace root to this app. A stray package-lock.json in a parent
  // directory otherwise makes Next infer the wrong root (see build warning).
  turbopack: {
    root: import.meta.dirname,
  },
};

export default nextConfig;
