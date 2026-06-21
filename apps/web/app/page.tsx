"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

// The root path mirrors the old SPA: redirect to /login. (The router guard and
// 401 handler then take over.) Client-side redirect because static export has no
// server runtime to issue one.
export default function Home() {
  const router = useRouter();
  React.useEffect(() => {
    router.replace("/login");
  }, [router]);
  return null;
}
