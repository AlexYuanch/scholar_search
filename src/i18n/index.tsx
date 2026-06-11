import { createContext, useContext, useState, useCallback, type ReactNode } from "react"
import zh from "./zh"
import en from "./en"

export type Lang = "zh" | "en"

const messages: Record<Lang, Record<string, string>> = { zh, en }

type I18nContextType = {
  lang: Lang
  t: (key: string) => string
  setLang: (lang: Lang) => void
}

const I18nContext = createContext<I18nContextType>({
  lang: "zh",
  t: (k: string) => k,
  setLang: () => {},
})

export function useTranslation() {
  return useContext(I18nContext)
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const saved = localStorage.getItem("lang") as Lang | null
    return saved === "en" ? "en" : "zh"
  })

  const setLang = useCallback((l: Lang) => {
    setLangState(l)
    localStorage.setItem("lang", l)
  }, [])

  const t = useCallback((key: string) => messages[lang][key] ?? key, [lang])

  return (
    <I18nContext.Provider value={{ lang, t, setLang }}>
      {children}
    </I18nContext.Provider>
  )
}
