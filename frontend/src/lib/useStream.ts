"use client";

import { useEffect, useRef, useState } from "react";

import { getCurrentReading, getStreamUrl } from "./api";
import type {
  ElectricalReading,
  StreamReadingEvent,
} from "../types/monitoring";
import { errorMessage } from "./usePoll";

export type RealtimeTransport = "sse" | "poll";

export interface RecentPoint {
  t: number;
  active_power: number;
}

interface StreamResult {
  reading: ElectricalReading | null;
  transport: RealtimeTransport;
  error: string | null;
  recent: RecentPoint[];
  loading: boolean;
}

/** Quantos pontos recentes o gráfico rolante guarda. */
const MAX_RECENT_POINTS = 120;

function appendRecent(
  prev: RecentPoint[],
  reading: ElectricalReading
): RecentPoint[] {
  const next = [
    ...prev,
    { t: Date.parse(reading.timestamp), active_power: reading.active_power },
  ];
  return next.length > MAX_RECENT_POINTS
    ? next.slice(next.length - MAX_RECENT_POINTS)
    : next;
}

/**
 * Leitura em tempo real com fallback automático.
 *
 * Tenta primeiro o stream SSE (GET /api/v1/stream/readings, ~1 Hz). Se o
 * EventSource falhar ou cair (ex.: proxy que bloqueia SSE), fecha o
 * stream e recorre ao polling de GET /api/monitoring/current no intervalo
 * configurado. O chamador mostra qual transporte está ativo.
 */
export function useRealtimeReading(
  pollIntervalMs: number,
  fallbackError: string
): StreamResult {
  const [reading, setReading] = useState<ElectricalReading | null>(null);
  const [transport, setTransport] = useState<RealtimeTransport>("sse");
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<RecentPoint[]>([]);
  const [loading, setLoading] = useState(true);

  const pollIntervalRef = useRef(pollIntervalMs);
  const fallbackRef = useRef(fallbackError);

  useEffect(() => {
    pollIntervalRef.current = pollIntervalMs;
    fallbackRef.current = fallbackError;
  });

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let pollId: ReturnType<typeof setInterval> | null = null;

    function ingest(next: ElectricalReading) {
      if (disposed) {
        return;
      }
      setReading(next);
      setRecent((prev) => appendRecent(prev, next));
      setError(null);
      setLoading(false);
    }

    function ingestError(err: unknown) {
      if (disposed) {
        return;
      }
      setError(errorMessage(err, fallbackRef.current));
      setLoading(false);
    }

    function startPolling() {
      setTransport("poll");
      async function tick() {
        try {
          ingest(await getCurrentReading());
        } catch (err) {
          ingestError(err);
        }
      }
      void tick();
      pollId = setInterval(tick, Math.max(pollIntervalRef.current, 1000));
    }

    // EventSource só existe no browser; em SSR, cai direto no polling.
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      startPolling();
      return () => {
        disposed = true;
        if (pollId) clearInterval(pollId);
      };
    }

    try {
      source = new EventSource(getStreamUrl("/api/v1/stream/readings"));
    } catch {
      source = null;
    }

    if (source === null) {
      startPolling();
    } else {
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          const data = JSON.parse(event.data) as StreamReadingEvent;
          if (data && data.reading) {
            ingest(data.reading);
          }
        } catch {
          // Linha malformada: ignora e espera a próxima.
        }
      };
      source.onerror = () => {
        // Stream indisponível/derrubado: fecha e recorre ao polling.
        try {
          source?.close();
        } catch {
          // noop
        }
        source = null;
        if (!disposed) {
          startPolling();
        }
      };
    }

    return () => {
      disposed = true;
      try {
        source?.close();
      } catch {
        // noop
      }
      if (pollId) {
        clearInterval(pollId);
      }
    };
    // Monta uma vez: o fallback é interno e não reinicia a conexão.
  }, []);

  return { reading, transport, error, recent, loading };
}
