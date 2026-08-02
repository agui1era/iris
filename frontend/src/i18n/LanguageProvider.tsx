import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { LanguageContext, type Language } from "./context";

const STORAGE_KEY = "iris.language";

function initialLanguage(): Language {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "es" || saved === "en") return saved;
  return navigator.language.toLowerCase().startsWith("es") ? "es" : "en";
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(initialLanguage);

  const setLanguage = useCallback((next: Language) => {
    localStorage.setItem(STORAGE_KEY, next);
    setLanguageState(next);
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const value = useMemo(
    () => ({
      language,
      locale: language === "es" ? ("es-CL" as const) : ("en-US" as const),
      setLanguage,
      t: (spanish: string, english: string) => (language === "es" ? spanish : english),
    }),
    [language, setLanguage],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
