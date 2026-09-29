import type { Preferences } from "./preferences";

/**
 * Formatação de números, datas e durações — sempre pt-BR por padrão,
 * respeitando a preferência de formato de data/hora do usuário.
 */

const numberFormatters = new Map<string, Intl.NumberFormat>();

function numberFormatter(digits: number): Intl.NumberFormat {
  const key = String(digits);
  let formatter = numberFormatters.get(key);
  if (!formatter) {
    formatter = new Intl.NumberFormat("pt-BR", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    numberFormatters.set(key, formatter);
  }
  return formatter;
}

export function formatNumber(
  value: number | null | undefined,
  digits = 1
): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "--";
  }
  return numberFormatter(digits).format(value);
}

export function formatDateTime(
  iso: string | null | undefined,
  prefs: Pick<Preferences, "datetimeFormat">
): string {
  if (!iso) {
    return "--";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  if (prefs.datetimeFormat === "iso") {
    return date.toISOString();
  }
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function formatTime(
  iso: string | null | undefined,
  prefs: Pick<Preferences, "datetimeFormat">
): string {
  if (!iso) {
    return "--";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "--";
  }
  if (prefs.datetimeFormat === "iso") {
    return date.toISOString().slice(11, 19);
  }
  return new Intl.DateTimeFormat("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/** "há 5 s" / "há 3 min" / "há 2 h" / "há 4 dias" / "agora mesmo". */
export function formatRelative(
  iso: string | null | undefined,
  justNow: string,
  templates: {
    secondsAgo: string;
    minutesAgo: string;
    hoursAgo: string;
    daysAgo: string;
  }
): string {
  if (!iso) {
    return "--";
  }
  const date = new Date(iso).getTime();
  if (Number.isNaN(date)) {
    return "--";
  }
  const diffS = Math.max(0, Math.round((Date.now() - date) / 1000));
  if (diffS < 5) {
    return justNow;
  }
  if (diffS < 60) {
    return templates.secondsAgo.replace("{n}", String(diffS));
  }
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) {
    return templates.minutesAgo.replace("{n}", String(diffM));
  }
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) {
    return templates.hoursAgo.replace("{n}", String(diffH));
  }
  return templates.daysAgo.replace(
    "{n}",
    String(Math.floor(diffH / 24))
  );
}

/** 3661s -> "1h 1min"; 90000s -> "1d 1h 0min". */
export function formatUptime(
  totalSeconds: number | null | undefined,
  templates: { full: string; short: string; minutes: string }
): string {
  if (
    totalSeconds === null ||
    totalSeconds === undefined ||
    Number.isNaN(totalSeconds)
  ) {
    return "--";
  }
  const s = Math.max(0, Math.floor(totalSeconds));
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) {
    return templates.full
      .replace("{d}", String(d))
      .replace("{h}", String(h))
      .replace("{m}", String(m));
  }
  if (h > 0) {
    return templates.short
      .replace("{h}", String(h))
      .replace("{m}", String(m));
  }
  return templates.minutes.replace("{m}", String(m));
}

export function formatBytes(bytes: number | null | undefined): string {
  if (
    bytes === null ||
    bytes === undefined ||
    Number.isNaN(bytes)
  ) {
    return "--";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kb = bytes / 1024;
  if (kb < 1024) {
    return `${formatNumber(kb, 1)} KB`;
  }
  return `${formatNumber(kb / 1024, 1)} MB`;
}
