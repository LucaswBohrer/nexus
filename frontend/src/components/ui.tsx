import type { ElementType, ReactNode } from "react";
import { AlertTriangle, Loader2 } from "lucide-react";

import { usePreferences } from "../lib/preferences";

/** Superfície temática (respeita data-theme). */
export function Card({
  children,
  className = "",
  id,
}: {
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <div id={id} className={`panel density-pad rounded-2xl ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({
  eyebrow,
  title,
  action,
}: {
  eyebrow: string;
  title: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-faint">
          {eyebrow}
        </p>
        <h3 className="mt-1 text-lg font-semibold tracking-tight text-ink">
          {title}
        </h3>
      </div>
      {action}
    </div>
  );
}

const badgeTones: Record<string, string> = {
  normal: "badge-green",
  info: "badge-blue",
  warning: "badge-amber",
  critical: "badge-red",
  open: "badge-amber",
  acknowledged: "badge-blue",
  resolved: "badge-green",
  low: "badge-green",
  medium: "badge-amber",
  high: "badge-red",
};

export function Badge({
  tone,
  children,
  icon: Icon,
}: {
  tone: string;
  children: ReactNode;
  icon?: ElementType;
}) {
  const cls = badgeTones[tone] ?? "badge-neutral";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${cls}`}
    >
      {Icon && <Icon size={13} />}
      {children}
    </span>
  );
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  const { t } = usePreferences();
  return (
    <div className="flex items-center gap-2 rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-sm text-amber-500">
      <AlertTriangle size={16} className="shrink-0" />
      <span className="min-w-0 flex-1">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-lg px-3 py-2 text-xs font-medium underline underline-offset-2"
        >
          {t.common.retry}
        </button>
      )}
    </div>
  );
}

export function LoadingState({ label }: { label?: string }) {
  const { t } = usePreferences();
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-faint">
      <Loader2 size={16} className="animate-spin" />
      {label ?? t.common.loading}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  message,
}: {
  icon: ElementType;
  title: string;
  message: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-3 text-faint">
        <Icon size={22} />
      </div>
      <p className="text-sm font-semibold text-ink">{title}</p>
      <p className="max-w-md text-sm text-muted">{message}</p>
    </div>
  );
}

/** Cabeçalho de página (título + subtítulo + ações). */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="truncate text-xl font-semibold tracking-tight text-ink sm:text-2xl">
          {title}
        </h2>
        {subtitle && (
          <p className="mt-1 text-sm text-muted">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2">{actions}</div>
      )}
    </div>
  );
}
