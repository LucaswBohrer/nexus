"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ElementType } from "react";
import {
  BarChart3,
  Bell,
  FileText,
  FlaskConical,
  History,
  LayoutDashboard,
  Loader2,
  MoreHorizontal,
  Radio,
  Server,
  Settings,
  ShieldCheck,
  Stethoscope,
  X,
  Zap,
} from "lucide-react";

import { getDiagnostics } from "../lib/api";
import { usePreferences } from "../lib/preferences";
import { EquipmentSelector } from "./EquipmentSelector";

interface NavItem {
  href: string;
  label: string;
  icon: ElementType;
}

function useNavItems(): NavItem[] {
  const { t } = usePreferences();
  return [
    { href: "/", label: t.nav.dashboard, icon: LayoutDashboard },
    { href: "/monitor", label: t.nav.monitor, icon: Radio },
    { href: "/history", label: t.nav.history, icon: History },
    { href: "/events", label: t.nav.events, icon: Bell },
    { href: "/diagnostics", label: t.nav.diagnostics, icon: Stethoscope },
    { href: "/analytics", label: t.nav.analytics, icon: BarChart3 },
    { href: "/simulation", label: t.nav.simulation, icon: FlaskConical },
    { href: "/reports", label: t.nav.reports, icon: FileText },
    { href: "/equipment", label: t.nav.equipment, icon: Server },
    { href: "/system", label: t.nav.system, icon: ShieldCheck },
    { href: "/settings", label: t.nav.settings, icon: Settings },
  ];
}

function titleForPath(pathname: string, items: NavItem[]): string {
  return (
    items.find((item) =>
      item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
    )?.label ?? "NEXUS"
  );
}

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/**
 * App shell: sidebar fixa no desktop, bottom bar no mobile.
 * O status geral no rodapé da sidebar vem do diagnóstico real do backend.
 */
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { t } = usePreferences();
  const items = useNavItems();

  const [systemNormal, setSystemNormal] = useState<boolean | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [moreOpen, setMoreOpen] = useState(false);

  // Status geral para o rodapé da sidebar + pílula de conexão.
  // Poll leve (30 s); as páginas fazem seu próprio polling de dados.
  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await getDiagnostics();
        if (!cancelled) {
          setSystemNormal(data.diagnosis.status === "normal");
          setConnected(true);
        }
      } catch {
        if (!cancelled) {
          setConnected(false);
        }
      }
    }
    poll();
    const id = setInterval(poll, 30000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // O menu "Mais" fecha ao tocar em um link (onClick abaixo) ou
  // no backdrop — sem setState dentro de effect.

  const mobilePrimary = items.slice(0, 4);
  const mobileMore = items.slice(4);

  const statusDot =
    connected === false
      ? "bg-[var(--bad)]"
      : systemNormal === false
        ? "bg-[var(--warn)]"
        : "bg-[var(--ok)]";

  return (
    <div className="min-h-screen">
      {/* SIDEBAR — desktop */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col border-r border-[var(--border)] bg-[var(--surface-2)] lg:flex">
        <div className="flex h-20 items-center gap-3 border-b border-[var(--border)] px-6">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-[var(--text)] text-[var(--bg)]">
            <Zap size={19} />
          </div>
          <div>
            <h1 className="text-lg font-semibold tracking-tight text-ink">
              {t.app.name}
            </h1>
            <p className="text-[10px] uppercase tracking-[0.2em] text-faint">
              {t.app.tagline}
            </p>
          </div>
        </div>

        {/* SELETOR DE EQUIPAMENTO — desktop (contexto global NEXUS 2.4) */}
        <div className="border-b border-[var(--border)] px-4 py-3">
          <p className="mb-2 px-1 text-[10px] font-semibold uppercase tracking-[0.2em] text-faint">
            {t.equipment.current}
          </p>
          <EquipmentSelector />
        </div>

        <nav className="flex-1 overflow-y-auto px-4 py-6">
          <p className="mb-3 px-3 text-[10px] font-semibold uppercase tracking-[0.2em] text-faint">
            {t.nav.sectionMonitoring}
          </p>
          {items.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`mt-1 flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${
                  active
                    ? "bg-[var(--surface-3)] text-ink"
                    : "text-muted hover:bg-[var(--surface-3)] hover:text-ink"
                }`}
              >
                <Icon size={17} className="shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="border-t border-[var(--border)] p-4">
          <div className="panel rounded-xl p-4">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${statusDot}`} />
              <span className="text-xs font-medium text-muted">
                {t.dashboard.overallStatus}
              </span>
            </div>
            <p
              className={`mt-2 text-sm font-medium ${
                systemNormal === false
                  ? "text-[var(--warn)]"
                  : "text-[var(--ok)]"
              }`}
            >
              {connected === false
                ? t.status.disconnected
                : systemNormal === false
                  ? t.status.attentionNeeded
                  : t.status.operational}
            </p>
          </div>
        </div>
      </aside>

      {/* CONTEÚDO */}
      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 border-b border-[var(--border)] bg-[var(--bg)]/90 backdrop-blur">
          <div className="flex min-h-16 items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <div className="flex min-w-0 items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--text)] text-[var(--bg)] lg:hidden">
                <Zap size={16} />
              </div>
              <h2 className="truncate text-base font-semibold tracking-tight text-ink sm:text-lg">
                {titleForPath(pathname, items)}
              </h2>
            </div>

            {/* Status de conexão — sempre visível, compacto no mobile */}
            <div className="flex shrink-0 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-xs text-muted">
              {connected === null ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <span
                  className={`h-2 w-2 rounded-full ${
                    connected ? "bg-[var(--ok)]" : "bg-[var(--bad)]"
                  }`}
                />
              )}
              <span className="hidden sm:inline">
                {connected === false
                  ? t.status.disconnected
                  : t.status.connected}
              </span>
            </div>
          </div>

          {/* SELETOR DE EQUIPAMENTO — mobile (contexto global NEXUS 2.4) */}
          <div className="border-t border-[var(--border)] px-4 py-2 lg:hidden">
            <EquipmentSelector compact />
          </div>
        </header>

        <main className="px-4 pb-[calc(56px+env(safe-area-inset-bottom)+2rem)] pt-4 sm:px-6 sm:pt-6 lg:pb-8">
          {children}
        </main>
      </div>

      {/* BOTTOM BAR — mobile */}
      <nav
        aria-label={t.nav.sectionMonitoring}
        className="fixed inset-x-0 bottom-0 z-40 border-t border-[var(--border)] bg-[var(--surface-2)] lg:hidden"
        style={{
          height: "calc(56px + env(safe-area-inset-bottom))",
          paddingBottom: "env(safe-area-inset-bottom)",
        }}
      >
        <div className="grid h-[56px] grid-cols-5">
          {mobilePrimary.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex min-h-[44px] flex-col items-center justify-center gap-1 text-[10px] font-medium ${
                  active ? "text-ink" : "text-faint"
                }`}
              >
                <Icon size={20} />
                {item.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            className={`flex min-h-[44px] flex-col items-center justify-center gap-1 text-[10px] font-medium ${
              mobileMore.some((item) => isActive(pathname, item.href))
                ? "text-ink"
                : "text-faint"
            }`}
            aria-haspopup="dialog"
          >
            <MoreHorizontal size={20} />
            {t.nav.more}
          </button>
        </div>
      </nav>

      {/* MENU "MAIS" — bottom sheet */}
      {moreOpen && (
        <div
          role="dialog"
          aria-modal="true"
          className="fixed inset-0 z-50 lg:hidden"
        >
          <button
            type="button"
            aria-label={t.common.close}
            className="absolute inset-0 bg-black/60"
            onClick={() => setMoreOpen(false)}
          />
          <div
            className="absolute inset-x-0 bottom-0 rounded-t-3xl border-t border-[var(--border)] bg-[var(--surface)]"
            style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
          >
            <div className="flex items-center justify-between px-5 pb-2 pt-4">
              <p className="text-sm font-semibold text-ink">{t.nav.more}</p>
              <button
                type="button"
                onClick={() => setMoreOpen(false)}
                aria-label={t.common.close}
                className="flex h-11 w-11 items-center justify-center rounded-full bg-[var(--surface-3)] text-muted"
              >
                <X size={18} />
              </button>
            </div>
            <nav className="px-3 pb-4">
              {mobileMore.map((item) => {
                const active = isActive(pathname, item.href);
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMoreOpen(false)}
                    className={`flex min-h-[52px] items-center gap-4 rounded-2xl px-4 text-sm font-medium ${
                      active
                        ? "bg-[var(--surface-3)] text-ink"
                        : "text-muted"
                    }`}
                  >
                    <Icon size={20} className="shrink-0" />
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
        </div>
      )}
    </div>
  );
}
