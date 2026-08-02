import { createContext } from "react";

export type Language = "es" | "en";

export interface LanguageContextValue {
  language: Language;
  locale: "es-CL" | "en-US";
  setLanguage: (language: Language) => void;
  t: (spanish: string, english: string) => string;
}

export const LanguageContext = createContext<LanguageContextValue | null>(null);
