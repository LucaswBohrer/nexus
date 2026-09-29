import { ptBR, type Dictionary } from "./pt-BR";

/**
 * Registro de idiomas. Hoje só pt-BR é enviado — adicionar um idioma
 * significa prover um dicionário completo do tipo `Dictionary`
 * (o type-check impede tradução parcial).
 */
const dictionaries = {
  "pt-BR": ptBR,
} as const;

export type Locale = keyof typeof dictionaries;

export const defaultLocale: Locale = "pt-BR";

export function getDictionary(locale: Locale): Dictionary {
  return dictionaries[locale] ?? ptBR;
}

export { ptBR };
export type { Dictionary };
