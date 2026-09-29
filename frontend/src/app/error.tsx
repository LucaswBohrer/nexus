"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

import { ptBR } from "../i18n";

// Route-level error boundary. Se a renderização quebrar (ex.: payload
// inesperado da API), exibe um fallback recuperável em vez de página em
// branco. Usa o dicionário diretamente (sem contexto) para funcionar
// mesmo se o provider tiver falhado.
export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error("Render error:", error);
  }, [error]);

  const t = ptBR;

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="panel w-full max-w-md rounded-2xl p-8 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-[var(--warn)]/10 text-[var(--warn)]">
          <AlertTriangle size={22} />
        </div>

        <h1 className="mt-4 text-lg font-semibold tracking-tight text-ink">
          {t.error.title}
        </h1>

        <p className="mt-2 text-sm text-muted">{t.error.message}</p>

        <button
          type="button"
          onClick={() => retry()}
          className="mt-6 min-h-[44px] w-full rounded-xl bg-[var(--info)] px-4 py-2.5 text-sm font-medium text-white transition"
        >
          {t.common.retry}
        </button>
      </div>
    </main>
  );
}
