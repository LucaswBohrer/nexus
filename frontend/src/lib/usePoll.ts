"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { ApiError } from "./api";

export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 401) {
      return "unauthorized";
    }
    return err.detail ?? fallback;
  }
  return fallback;
}

interface PollResult<T> {
  data: T | null;
  error: string | null;
  unauthorized: boolean;
  loading: boolean;
  refresh: () => void;
}

/**
 * Polling de dados com intervalo configurável.
 * `fn` pode ser inline: é guardada em ref para não reiniciar o intervalo.
 * intervalMs <= 0 desliga o polling automático (só carrega uma vez).
 */
export function usePoll<T>(
  fn: () => Promise<T>,
  intervalMs: number,
  fallbackError: string
): PollResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [loading, setLoading] = useState(true);

  const fnRef = useRef(fn);
  const fallbackRef = useRef(fallbackError);

  // Guarda os callbacks mais recentes sem reiniciar o intervalo.
  // (Atribuição de ref em effect — nunca durante o render.)
  useEffect(() => {
    fnRef.current = fn;
    fallbackRef.current = fallbackError;
  });

  const refresh = useCallback(() => {
    fnRef
      .current()
      .then((result) => {
        setData(result);
        setError(null);
        setUnauthorized(false);
      })
      .catch((err: unknown) => {
        // Em falha de poll, mantém os últimos dados válidos na tela.
        if (err instanceof ApiError && err.status === 401) {
          setUnauthorized(true);
          setError("unauthorized");
        } else {
          setError(errorMessage(err, fallbackRef.current));
        }
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    refresh();
    if (intervalMs <= 0) {
      return;
    }
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
  }, [refresh, intervalMs]);

  return { data, error, unauthorized, loading, refresh };
}

/** Relógio que força re-render a cada `intervalMs` (p/ "há X segundos"). */
export function useNow(intervalMs = 10000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
