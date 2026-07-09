/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const api =
      process.env.API_PROXY_TARGET ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${api}/api/:path*` },
    ];
  },
};
export default nextConfig;
