"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Loader2, Server } from "lucide-react";

import { useEquipment } from "../lib/equipment";
import { usePreferences } from "../lib/preferences";
import type { EquipmentStatus } from "../types/monitoring";
import { Badge } from "./ui";

/** Tom do badge por status operacional do equipamento. */
function statusTone(status: EquipmentStatus): string {
  switch (status) {
    case "active":
      return "normal";
    case "maintenance":
      return "warning";
    case "inactive":
      return "neutral";
    default:
      return "neutral";
  }
}

/**
 * Seletor global de equipamento (NEXUS 2.4).
 *
 * Usado na sidebar (desktop) e na barra sob o header (mobile). Uma única
 * fonte de estado via EquipmentContext — trocar aqui re-escopa todas as
 * páginas que consomem `equipmentId`.
 */
export function EquipmentSelector({ compact = false }: { compact?: boolean }) {
  const { t } = usePreferences();
  const { equipments, equipment, loading, error, select } = useEquipment();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Fecha ao clicar fora ou pressionar Escape.
  useEffect(() => {
    if (!open) {
      return;
    }
    function onPointerDown(event: PointerEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open ]);

  function handleSelect(id: number) {
    select(id);
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={t.equipment.select}
        disabled={loading}
        className={`flex min-h-[48px] w-full items-center gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 text-left transition hover:border-[var(--faint)] disabled:opacity-60 ${
          compact ? "py-2" : "py-2.5"
        }`}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-surface-3 text-muted">
          {loading ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <Server size={16} />
          )}
        </span>
        <span className="min-w-0 flex-1">
          <span
            className={`block truncate font-medium text-ink ${
              compact ? "text-xs" : "text-sm"
            }`}
          >
            {error
              ? t.equipment.listError
              : (equipment?.name ?? t.common.loading)}
          </span>
          {equipment && (
            <span className="mt-0.5 block truncate text-[11px] text-faint">
              {equipment.code}
              {equipment.enabled ? "" : ` · ${t.equipment.disabled}`}
            </span>
          )}
        </span>
        {equipment && (
          <span
            className={`h-2 w-2 shrink-0 rounded-full ${
              equipment.status === "active"
                ? "bg-[var(--ok)]"
                : equipment.status === "maintenance"
                  ? "bg-[var(--warn)]"
                  : "bg-[var(--faint)]"
            }`}
            aria-hidden
          />
        )}
        <ChevronDown
          size={16}
          className={`shrink-0 text-faint transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open && !loading && !error && (
        <div
          role="listbox"
          aria-label={t.equipment.select}
          className="absolute inset-x-0 top-full z-50 mt-2 max-h-80 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-1.5 shadow-xl"
        >
          {equipments.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-faint">
              {t.equipment.empty}
            </p>
          ) : (
            equipments.map((item) => {
              const selected = item.id === equipment?.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => handleSelect(item.id)}
                  className={`flex min-h-[52px] w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition ${
                    selected
                      ? "bg-surface-3"
                      : "hover:bg-surface-2"
                  }`}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-ink">
                      {item.name}
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-faint">
                      {item.code}
                      {item.location ? ` · ${item.location}` : ""}
                      {item.enabled ? "" : ` · ${t.equipment.disabled}`}
                    </span>
                  </span>
                  <Badge tone={statusTone(item.status)}>
                    {t.equipment.statuses[item.status] ?? item.status}
                  </Badge>
                  {selected && (
                    <Check
                      size={16}
                      className="shrink-0 text-[var(--info)]"
                    />
                  )}
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
