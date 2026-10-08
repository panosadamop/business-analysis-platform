import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useSession } from '../lib/store'
import { useI18n } from '../i18n'
import { LogoMark } from '../components/Logo'
import { ThemeToggle } from '../components/ThemeToggle'
import { ErrorBanner, Field, Note } from '../components/ui'

export function LoginPage() {
  const { t, locale, setLocale } = useI18n()
  const navigate = useNavigate()
  const signIn = useSession((state) => state.signIn)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  const providers = useQuery({
    queryKey: ['auth-providers'],
    queryFn: () => api<{ oidc: boolean; issuer: string | null; note: string }>(
      '/auth/providers'),
  })

  useEffect(() => {
    document.title = `${t('signIn')} · ${t('appName')}`
  }, [t])

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const user = await signIn(email, password)
      navigate(user.isClient ? '/client' : '/', { replace: true })
    } catch (caught) {
      setError(caught)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-ink-100 p-4">
      <div className="w-full max-w-md">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h1 className="flex items-center gap-2.5 text-lg font-semibold text-ink-900">
            <LogoMark size={36} />
            {t('appName')}
          </h1>
          <div className="flex items-center gap-2">
          <ThemeToggle />
          <div className="flex gap-1" role="group" aria-label="Interface language">
            {(['en', 'el'] as const).map((code) => (
              <button key={code} type="button" onClick={() => setLocale(code)}
                      aria-pressed={locale === code}
                      aria-label={code === 'en' ? 'English' : 'Ελληνικά'} lang={code}
                      className={`rounded px-2 py-1 text-xs font-medium ${
                        locale === code ? 'bg-brand-600 text-white' : 'text-ink-600'}`}>
                <span aria-hidden>{code.toUpperCase()}</span>
              </button>
            ))}
          </div>
          </div>
        </div>

        <form onSubmit={submit} className="card card-pad space-y-3">
          <Field label={t('email')}>
            <input className="input" type="email" autoComplete="username" required
                   value={email} onChange={(event) => setEmail(event.target.value)} />
          </Field>
          <Field label={t('password')}>
            <input className="input" type="password" autoComplete="current-password" required
                   value={password} onChange={(event) => setPassword(event.target.value)} />
          </Field>
          {error ? <ErrorBanner error={error} /> : null}
          <button type="submit" className="btn-primary w-full" disabled={busy}>
            {busy ? t('loading') : t('signIn')}
          </button>

          {providers.data?.oidc ? (
            <Note tone="muted">
              Company single sign on is configured ({providers.data.issuer}). Use it in
              production; local credentials exist for the initial deployment.
            </Note>
          ) : (
            <Note tone="muted">{providers.data?.note ?? ''}</Note>
          )}
        </form>
      </div>
    </main>
  )
}
