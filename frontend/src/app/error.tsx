"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

// Route-level error boundary for the dashboard. If rendering crashes
// (e.g. an unexpected API payload shape), show a recoverable fallback
// instead of a blank page.
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard render error:", error);
  }, [error]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[#090a0d] p-6 text-white">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#111318] p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400">
          <AlertTriangle size={22} />
        </div>

        <h1 className="mt-4 text-lg font-semibold tracking-tight">
          Something went wrong
        </h1>

        <p className="mt-2 text-sm text-gray-400">
          The dashboard hit an unexpected error. Your monitoring data is safe —
          try loading it again.
        </p>

        <button
          type="button"
          onClick={() => retry()}
          className="mt-6 w-full rounded-xl bg-white px-4 py-2.5 text-sm font-medium text-black transition hover:bg-gray-200"
        >
          Try again
        </button>
      </div>
    </main>
  );
}
