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

import {
  defaultLocale,
  getDictionary,
  type Dictionary,
  type Locale,
} from "../i18n";

/**
 * Preferências visuais do usuário — vivem em localStorage, NUNCA no banco.
 * (O banco guarda apenas settings operacionais via /api/v1/settings.)
 */
export interface Preferences {
  theme: "dark" | "light";
  language: Locale;
  datetimeFormat: "local" | "iso";
  defaultRange: "1h" | "6h" | "24h" | "7d";
  favoriteMetrics: string[];
  density: "comfortable" | "compact";
  /** Intervalo de polling em ms; 0 = atualização automática desligada. */
  pollingIntervalMs: number;
}

export const ALL_METRICS = [
  "voltage",
  "current",
  "active_power",
  "apparent_power",
  "temperature",
  "energy_today",
] as const;

export const POLLING_OPTIONS = [0, 2000, 5000, 10000, 30000] as const;

const STORAGE_KEY = "nexus:preferences:v1";

const DEFAULTS: Preferences = {
  theme: "dark",
  language: defaultLocale,
  datetimeFormat: "local",
  defaultRange: "24h",
  favoriteMetrics: [...ALL_METRICS],
  density: "comfortable",
  pollingIntervalMs: 5000,
};

function loadPreferences(): Preferences {
  if (typeof window === "undefined") {
    return DEFAULTS;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return DEFAULTS;
    }
    const parsed = JSON.parse(raw) as Partial<Preferences>;
    return {
      ...DEFAULTS,
      ...parsed,
      favoriteMetrics: Array.isArray(parsed.favoriteMetrics)
        ? parsed.favoriteMetrics.filter((m) =>
            (ALL_METRICS as readonly string[]).includes(m)
          )
        : DEFAULTS.favoriteMetrics,
    };
  } catch {
    return DEFAULTS;
  }
}

interface PreferencesContextValue {
  preferences: Preferences;
  updatePreferences: (patch: Partial<Preferences>) => void;
  t: Dictionary;
}

const PreferencesContext =
  createContext<PreferencesContextValue | null>(null);

export function PreferencesProvider({
  children,
}: {
  children: ReactNode;
}) {
  // O primeiro render (SSR e hidratação) usa sempre os padrões, para que
  // o HTML do cliente seja idêntico ao do servidor. As preferências salvas
  // são aplicadas num effect de montagem — sincronização pontual com um
  // sistema externo, o caso de uso legítimo para setState em effect.
  const [preferences, setPreferences] = useState<Preferences>(DEFAULTS);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPreferences(loadPreferences());
  }, []);

  // Sincroniza sistemas externos (DOM + persistência) — uso legítimo
  // de effect.
  useEffect(() => {
    try {
      window.localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(preferences)
      );
    } catch {
      // Armazenamento indisponível (modo privado etc.): segue sem persistir.
    }
    const root = document.documentElement;
    root.dataset.theme = preferences.theme;
    root.dataset.density = preferences.density;
    root.lang = preferences.language;
  }, [preferences]);

  const updatePreferences = useCallback(
    (patch: Partial<Preferences>) => {
      setPreferences((prev) => ({ ...prev, ...patch }));
    },
    []
  );

  const value = useMemo<PreferencesContextValue>(
    () => ({
      preferences,
      updatePreferences,
      t: getDictionary(preferences.language),
    }),
    [preferences, updatePreferences]
  );

  return (
    <PreferencesContext.Provider value={value}>
      {children}
    </PreferencesContext.Provider>
  );
}

export function usePreferences(): PreferencesContextValue {
  const ctx = useContext(PreferencesContext);
  if (!ctx) {
    throw new Error(
      "usePreferences must be used inside <PreferencesProvider>"
    );
  }
  return ctx;
}
