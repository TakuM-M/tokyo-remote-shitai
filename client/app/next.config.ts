import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'export',
  // Data files are in ../../data relative to this app directory
  // During development we serve them via rewrites or place symlinks
};

export default nextConfig;
