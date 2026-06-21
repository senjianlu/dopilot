/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: one HTML file per route, served by dopilot-server (FastAPI).
  // No `next start`, no Node production runtime (phase 2.1 hard constraint).
  output: "export",
  // trailingSlash emits `route/index.html`, which the FastAPI static resolver
  // maps `/dashboard/` -> `dashboard/index.html`. See apps/server .../app.py.
  trailingSlash: true,
  // next/image optimization needs a server; disable it for static export.
  images: { unoptimized: true },
  // Lint/typecheck are run as their own pnpm scripts in CI; don't fail the
  // static build on them (keeps `pnpm --filter web build` focused on output).
  eslint: { ignoreDuringBuilds: true },
};

export default nextConfig;
