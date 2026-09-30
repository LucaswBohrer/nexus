"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { listEquipment } from "./api";
import type { Equipment } from "../types/monitoring";

/**
 * Estado global do equipamento selecionado (NEXUS 2.4).
 *
 * Uma única fonte: todas as páginas leem `equipmentId` daqui e o passam
 * para as chamadas da API. A seleção persiste em localStorage; ao
 * carregar, resolve o id salvo ou recai para o equipamento DEFAULT
 * (dono dos dados pré-2.4). O backend continua sendo a fonte de verdade
 * dos dados — este contexto guarda apenas identidade/seleção.
 */
const STORAGE_KEY = "nexus:equipment:v1";
const DEFAULT_CODE = "DEFAULT";

interface EquipmentContextValue {
  equipments: Equipment[];
  equipment: Equipment | null;
  equipmentId: number | null;
  loading: boolean;
  error: string | null;
  select: (id: number) => void;
  refresh: () => Promise<void>;
}

const EquipmentContext =
  createContext<EquipmentContextValue | null>(null);

function loadStoredId(): number | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const id = Number(raw);
    return Number.isFinite(id) && id > 0 ? id : null;
  } catch {
    return null;
  }
}

function persistId(id: number) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(id));
  } catch {
    // Armazenamento indisponível: segue sem persistir.
  }
}

export function EquipmentProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [equipments, setEquipments] = useState<Equipment[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listEquipment();
      setEquipments(list);
      setSelectedId((prev) => {
        // Mantém a seleção atual se ela ainda existir na lista.
        if (prev !== null && list.some((e) => e.id === prev)) {
          return prev;
        }
        const stored = loadStoredId();
        if (stored !== null && list.some((e) => e.id === stored)) {
          return stored;
        }
        // Recai para o DEFAULT (dados históricos) ou o primeiro.
        const fallback =
          list.find((e) => e.code === DEFAULT_CODE) ?? list[0] ?? null;
        return fallback ? fallback.id : null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "load-failed");
    } finally {
      setLoading(false);
    }
  }, []);

  // Busca inicial na montagem — sincronização pontual com um sistema
  // externo (a API), o caso de uso legítimo para setState em effect.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const select = useCallback((id: number) => {
    setSelectedId(id);
    persistId(id);
  }, []);

  const equipment = useMemo(
    () => equipments.find((e) => e.id === selectedId) ?? null,
    [equipments, selectedId]
  );

  const value = useMemo<EquipmentContextValue>(
    () => ({
      equipments,
      equipment,
      equipmentId: equipment?.id ?? null,
      loading,
      error,
      select,
      refresh: load,
    }),
    [equipments, equipment, loading, error, select, load]
  );

  return (
    <EquipmentContext.Provider value={value}>
      {children}
    </EquipmentContext.Provider>
  );
}

export function useEquipment(): EquipmentContextValue {
  const ctx = useContext(EquipmentContext);
  if (!ctx) {
    throw new Error(
      "useEquipment must be used inside <EquipmentProvider>"
    );
  }
  return ctx;
}
