/**
 * Colour theme preference: follow the operating system, or a fixed light or
 * dark theme.
 *
 * The choice is stored per browser and applied as data-theme on <html>; the
 * colour tokens in src/theme.css do the rest. index.html applies the stored
 * choice before the first paint so a dark theme never flashes light.
 */
import { create } from 'zustand'

export type ThemePreference = 'system' | 'light' | 'dark'

export const THEME_STORAGE_KEY = 'ait.theme'

function readStored(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* storage may be unavailable */
  }
  return 'system'
}

export function applyTheme(preference: ThemePreference) {
  const root = document.documentElement
  if (preference === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', preference)
}

interface ThemeState {
  preference: ThemePreference
  setPreference: (preference: ThemePreference) => void
}

export const useTheme = create<ThemeState>((set) => ({
  preference: readStored(),
  setPreference: (preference) => {
    try {
      if (preference === 'system') localStorage.removeItem(THEME_STORAGE_KEY)
      else localStorage.setItem(THEME_STORAGE_KEY, preference)
    } catch {
      /* the choice still applies for this visit */
    }
    applyTheme(preference)
    set({ preference })
  },
}))
