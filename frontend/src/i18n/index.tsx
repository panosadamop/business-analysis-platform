/**
 * Greek and English interface support (section 2).
 *
 * The interface language is independent of the project's output language and of
 * the language of the evidence.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { el } from './el'
import { en } from './en'

export type Locale = 'en' | 'el'
export type Dictionary = Record<keyof typeof en, string>

const DICTIONARIES: Record<Locale, Dictionary> = { en, el }
const STORAGE_KEY = 'ait.locale'

interface I18nValue {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: keyof Dictionary, vars?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nValue | null>(null)

function readStored(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'en' || stored === 'el') return stored
  } catch {
    /* storage may be unavailable */
  }
  return navigator.language?.toLowerCase().startsWith('el') ? 'el' : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStored)

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      /* ignore */
    }
  }, [])

  // The page language always matches the interface language (3.1.1).
  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const t = useCallback(
    (key: keyof Dictionary, vars?: Record<string, string | number>) => {
      const dictionary = DICTIONARIES[locale]
      let value = (dictionary[key] ?? en[key] ?? String(key)) as string
      if (vars) {
        for (const [name, replacement] of Object.entries(vars)) {
          value = value.replace(new RegExp(`\\{${name}\\}`, 'g'), String(replacement))
        }
      }
      return value
    },
    [locale],
  )

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside I18nProvider')
  return context
}

export function useT() {
  return useI18n().t
}
