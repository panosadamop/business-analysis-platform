/** Light, dark or match the operating system: a three way toggle. */
import { useT } from '../i18n'
import { useTheme } from '../lib/theme'
import type { ThemePreference } from '../lib/theme'

const OPTIONS: { value: ThemePreference; icon: string; labelKey: 'themeSystem' | 'themeLight' | 'themeDark' }[] = [
  { value: 'system', icon: '◐', labelKey: 'themeSystem' },
  { value: 'light', icon: '☀', labelKey: 'themeLight' },
  { value: 'dark', icon: '☾', labelKey: 'themeDark' },
]

export function ThemeToggle() {
  const t = useT()
  const { preference, setPreference } = useTheme()
  return (
    <div className="inline-flex rounded-lg border border-ink-200 p-0.5" role="group"
         aria-label={t('theme')}>
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => setPreference(option.value)}
          aria-pressed={preference === option.value}
          aria-label={t(option.labelKey)}
          title={t(option.labelKey)}
          className={`rounded-md px-2 py-0.5 text-sm leading-6 ${
            preference === option.value
              ? 'bg-brand-600 text-white'
              : 'text-ink-600 hover:bg-ink-100'}`}
        >
          <span aria-hidden>{option.icon}</span>
        </button>
      ))}
    </div>
  )
}
