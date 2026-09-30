"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Pencil,
  Plus,
  Power,
  PowerOff,
  Server,
  Trash2,
  X,
} from "lucide-react";

import {
  ApiError,
  createEquipment,
  deleteEquipment,
  getEquipmentSummary,
  updateEquipment,
} from "../../lib/api";
import { useEquipment } from "../../lib/equipment";
import { usePreferences } from "../../lib/preferences";
import { formatDateTime, formatNumber } from "../../lib/format";
import { errorMessage } from "../../lib/usePoll";
import type {
  Equipment,
  EquipmentCreatePayload,
  EquipmentStatus,
  EquipmentSummary,
  EquipmentUpdatePayload,
} from "../../types/monitoring";
import {
  Badge,
  Card,
  EmptyState,
  ErrorBanner,
  LoadingState,
  PageHeader,
} from "../../components/ui";

const STATUSES: EquipmentStatus[] = ["active", "inactive", "maintenance"];

function statusTone(status: EquipmentStatus): string {
  switch (status) {
    case "active":
      return "normal";
    case "maintenance":
      return "warning";
    default:
      return "neutral";
  }
}

interface FormState {
  name: string;
  code: string;
  description: string;
  equipment_type: string;
  location: string;
  status: EquipmentStatus;
  enabled: boolean;
}

function emptyForm(): FormState {
  return {
    name: "",
    code: "",
    description: "",
    equipment_type: "",
    location: "",
    status: "active",
    enabled: true,
  };
}

function formFrom(equipment: Equipment): FormState {
  return {
    name: equipment.name,
    code: equipment.code,
    description: equipment.description ?? "",
    equipment_type: equipment.equipment_type ?? "",
    location: equipment.location ?? "",
    status: equipment.status,
    enabled: equipment.enabled,
  };
}

function EquipmentFormModal({
  initial,
  editing,
  onClose,
  onSaved,
}: {
  initial: FormState;
  editing: Equipment | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = usePreferences();
  const [form, setForm] = useState<FormState>(initial);
  const [fieldErrors, setFieldErrors] = useState<{
    name?: string;
    code?: string;
  }>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const errors: { name?: string; code?: string } = {};
    if (!form.name.trim()) {
      errors.name = t.equipment.nameRequired;
    }
    if (!form.code.trim()) {
      errors.code = t.equipment.codeRequired;
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }

    setSaving(true);
    setSubmitError(null);
    const opt = (v: string) => (v.trim() ? v.trim() : null);
    try {
      if (editing) {
        const payload: EquipmentUpdatePayload = {
          name: form.name.trim(),
          code: form.code.trim(),
          description: opt(form.description),
          equipment_type: opt(form.equipment_type),
          location: opt(form.location),
          status: form.status,
          enabled: form.enabled,
        };
        await updateEquipment(editing.id, payload);
      } else {
        const payload: EquipmentCreatePayload = {
          name: form.name.trim(),
          code: form.code.trim(),
          description: opt(form.description),
          equipment_type: opt(form.equipment_type),
          location: opt(form.location),
          status: form.status,
          enabled: form.enabled,
        };
        await createEquipment(payload);
      }
      onSaved();
    } catch (err) {
      setSubmitError(
        errorMessage(
          err,
          editing ? t.equipment.updateError : t.equipment.createError
        )
      );
    } finally {
      setSaving(false);
    }
  }

  const inputClass =
    "h-11 w-full rounded-xl border border-[var(--faint)] bg-surface-2 px-3 text-sm text-ink";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={editing ? t.equipment.edit : t.equipment.create}
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
    >
      <button
        type="button"
        aria-label={t.common.close}
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
      />
      <div className="relative max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-t-3xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:rounded-3xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">
            {editing ? t.equipment.edit : t.equipment.create}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t.common.close}
            className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-3)] text-muted"
          >
            <X size={18} />
          </button>
        </div>

        {submitError && <ErrorBanner message={submitError} />}

        <form onSubmit={handleSubmit} className="mt-3 space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
                {t.equipment.name} *
              </span>
              <input
                className={inputClass}
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                maxLength={120}
                autoComplete="off"
              />
              {fieldErrors.name && (
                <span className="mt-1 block text-xs text-[var(--bad)]">
                  {fieldErrors.name}
                </span>
              )}
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
                {t.equipment.code} *
              </span>
              <input
                className={inputClass}
                value={form.code}
                onChange={(e) => set("code", e.target.value)}
                maxLength={64}
                autoComplete="off"
                placeholder="UPS-01"
              />
              {fieldErrors.code ? (
                <span className="mt-1 block text-xs text-[var(--bad)]">
                  {fieldErrors.code}
                </span>
              ) : (
                <span className="mt-1 block text-xs text-faint">
                  {t.equipment.codeHint}
                </span>
              )}
            </label>
          </div>

          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
              {t.equipment.description}
            </span>
            <textarea
              className="min-h-[76px] w-full rounded-xl border border-[var(--faint)] bg-surface-2 px-3 py-2.5 text-sm text-ink"
              value={form.description}
              onChange={(e) => set("description", e.target.value)}
              maxLength={500}
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
                {t.equipment.type}
              </span>
              <input
                className={inputClass}
                value={form.equipment_type}
                onChange={(e) => set("equipment_type", e.target.value)}
                maxLength={64}
                autoComplete="off"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
                {t.equipment.location}
              </span>
              <input
                className={inputClass}
                value={form.location}
                onChange={(e) => set("location", e.target.value)}
                maxLength={120}
                autoComplete="off"
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-faint">
                {t.equipment.status}
              </span>
              <select
                className={inputClass}
                value={form.status}
                onChange={(e) => set("status", e.target.value as EquipmentStatus)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {t.equipment.statuses[s]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-h-[44px] cursor-pointer items-center gap-3 pt-5">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => set("enabled", e.target.checked)}
                className="h-5 w-5 accent-[var(--info)]"
              />
              <span className="text-sm text-ink">{t.equipment.enabled}</span>
            </label>
          </div>

          <div className="flex flex-col gap-2 pt-1 sm:flex-row">
            <button
              type="button"
              onClick={onClose}
              className="flex min-h-[48px] flex-1 items-center justify-center rounded-2xl bg-surface-3 px-6 text-sm font-semibold text-ink"
            >
              {t.common.cancel}
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex min-h-[48px] flex-1 items-center justify-center rounded-2xl bg-[var(--info)] px-6 text-sm font-semibold text-white disabled:opacity-60"
            >
              {saving ? t.common.saving : t.common.save}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function DeleteConfirm({
  equipment,
  onClose,
  onDeleted,
}: {
  equipment: Equipment;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const { t } = usePreferences();
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    setError(null);
    try {
      await deleteEquipment(equipment.id);
      onDeleted();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? t.equipment.deleteConflict
          : errorMessage(err, t.equipment.deleteError)
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t.equipment.deleteConfirmTitle}
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center"
    >
      <button
        type="button"
        aria-label={t.common.close}
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md rounded-t-3xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:rounded-3xl">
        <h2 className="text-lg font-semibold text-ink">
          {t.equipment.deleteConfirmTitle}
        </h2>
        <p className="mt-2 text-sm text-muted">
          <span className="font-medium text-ink">{equipment.name}</span>
          {" · "}
          {equipment.code}
        </p>
        <p className="mt-2 text-xs text-faint">
          {t.equipment.deleteConfirmBody}
        </p>
        {error && (
          <div className="mt-3">
            <ErrorBanner message={error} />
          </div>
        )}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={onClose}
            className="flex min-h-[48px] flex-1 items-center justify-center rounded-2xl bg-surface-3 px-6 text-sm font-semibold text-ink"
          >
            {t.common.cancel}
          </button>
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleting}
            className="flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl bg-[var(--bad)] px-6 text-sm font-semibold text-white disabled:opacity-60"
          >
            <Trash2 size={16} />
            {deleting ? t.common.saving : t.equipment.delete}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function EquipmentPage() {
  const { t, preferences } = usePreferences();
  const { equipments, loading, error, refresh, select, equipmentId } =
    useEquipment();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Equipment | null>(null);
  const [deleting, setDeleting] = useState<Equipment | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<number | null>(null);
  const [summaries, setSummaries] = useState<
    Record<number, EquipmentSummary>
  >({});

  // Última leitura por equipamento (dados reais do summary). Sem isso,
  // a lista não mostraria o estado atual de cada fonte.
  useEffect(() => {
    if (equipments.length === 0) {
      return;
    }
    let cancelled = false;
    void Promise.allSettled(
      equipments.map((item) => getEquipmentSummary(item.id))
    ).then((results) => {
      if (cancelled) {
        return;
      }
      const map: Record<number, EquipmentSummary> = {};
      results.forEach((result, index) => {
        if (result.status === "fulfilled") {
          map[equipments[index].id] = result.value;
        }
      });
      setSummaries(map);
    });
    return () => {
      cancelled = true;
    };
  }, [equipments]);

  function openCreate() {
    setEditing(null);
    setFormOpen(true);
  }

  function openEdit(item: Equipment) {
    setEditing(item);
    setFormOpen(true);
  }

  async function handleSaved() {
    setFormOpen(false);
    setEditing(null);
    await refresh();
  }

  async function handleDeleted() {
    setDeleting(null);
    await refresh();
  }

  async function toggleEnabled(item: Equipment) {
    setToggling(item.id);
    setActionError(null);
    try {
      await updateEquipment(item.id, { enabled: !item.enabled });
      await refresh();
    } catch (err) {
      setActionError(errorMessage(err, t.equipment.toggleError));
    } finally {
      setToggling(null);
    }
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={t.equipment.title}
        subtitle={t.equipment.subtitle}
        actions={
          <button
            type="button"
            onClick={openCreate}
            className="flex min-h-[48px] items-center gap-2 rounded-2xl bg-[var(--info)] px-5 text-sm font-semibold text-white"
          >
            <Plus size={18} />
            {t.equipment.create}
          </button>
        }
      />

      {error && <ErrorBanner message={error} onRetry={() => void refresh()} />}
      {actionError && <ErrorBanner message={actionError} />}

      {loading && equipments.length === 0 ? (
        <LoadingState />
      ) : equipments.length === 0 ? (
        <Card>
          <EmptyState
            icon={Server}
            title={t.equipment.empty}
            message={t.equipment.emptyHint}
          />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {equipments.map((item) => {
            const isCurrent = item.id === equipmentId;
            const summary = summaries[item.id];
            const last = summary?.last_reading ?? null;
            return (
              <Card key={item.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold text-ink">
                      {item.name}
                    </p>
                    <p className="mt-0.5 truncate text-xs text-faint">
                      {item.code}
                      {item.location ? ` · ${item.location}` : ""}
                    </p>
                  </div>
                  {isCurrent && (
                    <Badge tone="info">{t.equipment.current}</Badge>
                  )}
                </div>

                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge tone={statusTone(item.status)}>
                    {t.equipment.statuses[item.status] ?? item.status}
                  </Badge>
                  <Badge tone={item.enabled ? "normal" : "neutral"}>
                    {item.enabled
                      ? t.equipment.enabled
                      : t.equipment.disabled}
                  </Badge>
                  {item.code === "DEFAULT" && (
                    <Badge tone="info">{t.equipment.defaultBadge}</Badge>
                  )}
                </div>

                {item.description && (
                  <p className="mt-3 line-clamp-2 text-sm text-muted">
                    {item.description}
                  </p>
                )}
                {item.equipment_type && (
                  <p className="mt-1 text-xs text-faint">
                    {t.equipment.type}: {item.equipment_type}
                  </p>
                )}

                <div className="mt-3 rounded-xl bg-surface-2 px-4 py-3">
                  <p className="text-[11px] uppercase tracking-wider text-faint">
                    {t.equipment.lastReading}
                  </p>
                  {!summary ? (
                    <p className="mt-1 text-xs text-faint">
                      {t.common.loading}
                    </p>
                  ) : last ? (
                    <>
                      <p className="mt-1 text-sm font-semibold text-ink">
                        {formatNumber(last.voltage, 1)} V ·{" "}
                        {formatNumber(last.current, 1)} A ·{" "}
                        {formatNumber(last.active_power, 2)} kW
                      </p>
                      <p className="mt-0.5 text-xs text-faint">
                        {t.common.lastUpdate}:{" "}
                        {formatDateTime(last.timestamp, preferences)}
                      </p>
                    </>
                  ) : (
                    <p className="mt-1 text-xs text-faint">
                      {t.equipment.noLastReading}
                    </p>
                  )}
                </div>

                <div className="mt-4 grid grid-cols-2 gap-2">
                  <Link
                    href={`/equipment/${item.id}`}
                    onClick={() => select(item.id)}
                    className="flex min-h-[44px] items-center justify-center rounded-xl bg-[var(--info)] px-3 text-sm font-semibold text-white"
                  >
                    {t.equipment.details}
                  </Link>
                  <button
                    type="button"
                    onClick={() => openEdit(item)}
                    className="flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-surface-3 px-3 text-sm font-medium text-ink"
                  >
                    <Pencil size={15} />
                    {t.common.edit}
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleEnabled(item)}
                    disabled={toggling === item.id}
                    className="flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-surface-3 px-3 text-sm font-medium text-ink disabled:opacity-60"
                  >
                    {item.enabled ? (
                      <PowerOff size={15} />
                    ) : (
                      <Power size={15} />
                    )}
                    {item.enabled
                      ? t.equipment.deactivate
                      : t.equipment.activate}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleting(item)}
                    className="flex min-h-[44px] items-center justify-center gap-1.5 rounded-xl bg-surface-3 px-3 text-sm font-medium text-[var(--bad)]"
                  >
                    <Trash2 size={15} />
                    {t.equipment.delete}
                  </button>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {formOpen && (
        <EquipmentFormModal
          initial={editing ? formFrom(editing) : emptyForm()}
          editing={editing}
          onClose={() => {
            setFormOpen(false);
            setEditing(null);
          }}
          onSaved={() => void handleSaved()}
        />
      )}

      {deleting && (
        <DeleteConfirm
          equipment={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={() => void handleDeleted()}
        />
      )}
    </div>
  );
}
