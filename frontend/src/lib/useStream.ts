"use client";

import { useEffect, useRef, useState } from "react";

import { getCurrentReading, getEquipmentSummary, getStreamUrl } from "./api";
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
 * stream e recorre ao polling no intervalo configurado. O chamador mostra
 * qual transporte está ativo.
 *
 * NEXUS 2.4: `equipmentId` escopa o stream (`?equipment_id=`); quando
 * muda, a conexão é refeita e o estado anterior é descartado (sem misturar
 * dados de equipamentos). No fallback de polling, a última leitura vem do
 * summary do equipamento. Omitido = equipamento DEFAULT (legado).
 */
export function useRealtimeReading(
  pollIntervalMs: number,
  fallbackError: string,
  equipmentId?: number | string | null
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
          if (equipmentId !== undefined && equipmentId !== null) {
            // Fallback por equipamento: última leitura real armazenada.
            const summary = await getEquipmentSummary(equipmentId);
            if (summary.last_reading) {
              ingest(summary.last_reading);
            } else {
              // Equipamento sem dados: estado vazio honesto, sem erro.
              if (!disposed) {
                setLoading(false);
              }
            }
          } else {
            ingest(await getCurrentReading());
          }
        } catch (err) {
          ingestError(err);
        }
      }
      void tick();
      pollId = setInterval(tick, Math.max(pollIntervalRef.current, 1000));
    }

    // Troca de equipamento: descarta o estado anterior antes de
    // reconectar — nunca mistura leituras de equipamentos diferentes.
    // (Sincronização com sistema externo: uso legítimo de setState em effect.)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReading(null);
    setRecent([]);
    setError(null);
    setLoading(true);
    setTransport("sse");

    // EventSource só existe no browser; em SSR, cai direto no polling.
    if (typeof window === "undefined" || typeof EventSource === "undefined") {
      startPolling();
      return () => {
        disposed = true;
        if (pollId) clearInterval(pollId);
      };
    }

    try {
      const streamPath =
        equipmentId !== undefined && equipmentId !== null
          ? `/api/v1/stream/readings?equipment_id=${encodeURIComponent(String(equipmentId))}`
          : "/api/v1/stream/readings";
      source = new EventSource(getStreamUrl(streamPath));
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
    // Reconecta quando o equipamento muda; o fallback interno (polling)
    // continua sem reiniciar a conexão por conta própria.
  }, [equipmentId]);

  return { reading, transport, error, recent, loading };
}
