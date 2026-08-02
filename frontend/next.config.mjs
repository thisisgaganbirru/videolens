/** @type {import('next').NextConfig} */
const nextConfig = {
  output: process.env.CAPACITOR_BUILD === "true" ? "export" : "standalone",
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
