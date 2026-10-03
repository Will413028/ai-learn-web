import type { NextConfig } from "next";

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${process.env.API_UPSTREAM ?? "http://127.0.0.1:8100"}/api/v1/:path*` }];
  },
};
export default config;
