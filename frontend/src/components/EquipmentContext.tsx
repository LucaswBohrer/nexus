"use client";

import { Server } from "lucide-react";

import { useEquipment } from "../lib/equipment";
import { usePreferences } from "../lib/preferences";

/**
 * Linha de contexto exibida no topo das páginas de dados: mostra o
 * equipamento atualmente selecionado. A seleção é global
 * (EquipmentProvider) — esta linha apenas a torna explícita na página.
 */
export function EquipmentContextLine() {
  const { t } = usePreferences();
  const { equipment, loading } = useEquipment();

  if (loading || !equipment) {
    return null;
  }

  return (
    <p className="flex items-center gap-1.5 text-xs text-faint">
      <Server size={13} className="shrink-0" />
      <span>
        {t.dashboard.currentEquipment}:{" "}
        <span className="font-medium text-muted">
          {equipment.name} · {equipment.code}
        </span>
        {!equipment.enabled && (
          <span className="text-[var(--warn)]">
            {" "}
            ({t.equipment.disabled})
          </span>
        )}
      </span>
    </p>
  );
}
