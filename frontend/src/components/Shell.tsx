/** Application shell: project switcher, the fourteen workspaces, language toggle. */
import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { api } from '../lib/api'
import { useSession } from '../lib/store'
import { useI18n } from '../i18n'
import type { Dictionary } from '../i18n'
import type { Project, ProjectHealth } from '../types'
import { LogoMark } from './Logo'
import { ThemeToggle } from './ThemeToggle'
import { Badge } from './ui'

interface NavItem {
  to: string
  labelKey: keyof Dictionary
  group: 'analysis' | 'delivery' | 'outward'
}

const PROJECT_NAV: NavItem[] = [
  { to: 'setup', labelKey: 'navSetup', group: 'analysis' },
  { to: 'evidence', labelKey: 'navEvidence', group: 'analysis' },
  { to: 'analysis', labelKey: 'navAnalysis', group: 'analysis' },
  { to: 'backlog', labelKey: 'navBacklog', group: 'analysis' },
  { to: 'specifications', labelKey: 'navSpecifications', group: 'analysis' },
  { to: 'approvals', labelKey: 'navApprovals', group: 'analysis' },
  { to: 'planning', labelKey: 'navPlanning', group: 'delivery' },
  { to: 'testbook', labelKey: 'navTestbook', group: 'delivery' },
  { to: 'dashboards', labelKey: 'navDashboards', group: 'delivery' },
  { to: 'reports', labelKey: 'navReports', group: 'delivery' },
  { to: 'integrations', labelKey: 'navIntegrations', group: 'outward' },
  { to: 'sharing', labelKey: 'navClient', group: 'outward' },
]

const LANGUAGE_NAMES: Record<'en' | 'el', string> = { en: 'English', el: 'Ελληνικά' }

const GROUP_LABELS: Record<NavItem['group'], string> = {
  analysis: 'Analysis',
  delivery: 'Delivery',
  outward: 'Outward facing',
}

export function Shell() {
  const { projectId } = useParams()
  const { user, signOut } = useSession()
  const { t, locale, setLocale } = useI18n()
  const navigate = useNavigate()
  const [pickedProject, setPickedProject] = useState(projectId ?? '')
  useEffect(() => setPickedProject(projectId ?? ''), [projectId])

  // After a client side navigation, move focus to the new screen so keyboard
  // and screen reader users start at its content (2.4.3).
  const { pathname } = useLocation()
  const mainRef = useRef<HTMLElement>(null)
  const firstRender = useRef(true)
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    mainRef.current?.focus()
  }, [pathname])

  // Below the desktop breakpoint the navigation folds behind a menu button, so
  // a phone opens on the screen's content rather than a full height sidebar.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  useEffect(() => setMenuOpen(false), [pathname])
  useEffect(() => {
    if (!menuOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setMenuOpen(false)
      menuButtonRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  const projects = useQuery({
    queryKey: ['projects'],
    queryFn: () => api<ProjectHealth[]>('/projects'),
    enabled: !user?.isClient,
  })

  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api<Project>(`/projects/${projectId}`),
    enabled: Boolean(projectId) && !user?.isClient,
  })

  return (
    <div className="min-h-screen lg:flex">
      {/* Bypass block (WCAG 2.4.1): the first tab stop jumps past the navigation. */}
      <a href="#main-content"
         className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60]
                    focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:text-sm
                    focus:font-medium focus:text-brand-800 focus:shadow">
        Skip to main content
      </a>
      <aside className="sticky top-0 z-40 border-b border-ink-200 bg-surface lg:static
                        lg:min-h-screen lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-2 px-4 py-3 lg:py-4">
          <NavLink to="/" className="flex min-w-0 items-center gap-2 rounded-lg text-sm
                                     font-semibold text-ink-900">
            <LogoMark size={28} />
            <span className="truncate">{t('appName')}</span>
          </NavLink>
          <div className="flex items-center gap-1">
          <div className="flex gap-1" role="group" aria-label="Interface language">
            {(['en', 'el'] as const).map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => setLocale(code)}
                aria-pressed={locale === code}
                aria-label={LANGUAGE_NAMES[code]}
                lang={code}
                className={`rounded px-1.5 py-0.5 text-xs font-medium ${
                  locale === code ? 'bg-brand-600 text-white' : 'text-ink-600 hover:bg-ink-100'
                }`}
              >
                <span aria-hidden>{code.toUpperCase()}</span>
              </button>
            ))}
          </div>
          <button
            ref={menuButtonRef}
            type="button"
            className="btn-ghost ml-1 px-2 py-1.5 lg:hidden"
            aria-expanded={menuOpen}
            aria-controls="app-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <span aria-hidden className="text-base leading-none">{menuOpen ? '✕' : '☰'}</span>
            <span className="text-xs">Menu</span>
          </button>
          </div>
        </div>

        <div id="app-menu"
             className={`${menuOpen ? 'block' : 'hidden'} max-h-[calc(100dvh-3.5rem)]
                         overflow-y-auto border-t border-ink-200 lg:block lg:max-h-none
                         lg:overflow-visible lg:border-t-0`}>
        <nav className="px-2 pb-4 pt-2 lg:pt-0" aria-label="Main">
          <NavLink to="/" end className={navClass}>
            <span aria-hidden>▦</span> {t('navPortfolio')}
          </NavLink>

          {!user?.isClient && projects.data?.length ? (
            <form
              className="mt-3 px-2"
              // Choosing a project does not navigate by itself; the Open button
              // does, so moving through the options never changes context (3.2.2).
              onSubmit={(event) => {
                event.preventDefault()
                if (pickedProject && pickedProject !== projectId) {
                  navigate(`/projects/${pickedProject}/evidence`)
                }
              }}
            >
              <label className="label mb-1" htmlFor="project-switcher">Project</label>
              <div className="flex gap-1">
              <select
                id="project-switcher"
                className="input"
                value={pickedProject}
                onChange={(event) => setPickedProject(event.target.value)}
              >
                <option value="">Select a project…</option>
                {projects.data.map((item) => (
                  <option key={item.projectId} value={item.projectId}>
                    {item.key} — {item.name}
                  </option>
                ))}
              </select>
              <button type="submit" className="btn-secondary px-2 text-xs"
                      disabled={!pickedProject || pickedProject === projectId}>
                Open
              </button>
              </div>
            </form>
          ) : null}

          {projectId && !user?.isClient ? (
            <div className="mt-3 space-y-3">
              {(['analysis', 'delivery', 'outward'] as const).map((group) => (
                <div key={group}>
                  <h2 id={`nav-group-${group}`}
                      className="px-3 pb-1 text-[11px] font-semibold uppercase
                                 tracking-wide text-ink-600">
                    {GROUP_LABELS[group]}
                  </h2>
                  {PROJECT_NAV.filter((item) => item.group === group).map((item) => (
                    <NavLink key={item.to} to={`/projects/${projectId}/${item.to}`}
                             className={navClass}>
                      {t(item.labelKey)}
                    </NavLink>
                  ))}
                </div>
              ))}
            </div>
          ) : null}

          {user?.isClient ? (
            <NavLink to="/client" className={navClass}>{t('navClient')}</NavLink>
          ) : null}

          {user?.globalRoles.some((role) =>
            role === 'system_admin' || role === 'superuser') ? (
            <div className="mt-3">
              <h2 className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide
                             text-ink-600">System</h2>
              <NavLink to="/admin" className={navClass}>{t('navAdmin')}</NavLink>
            </div>
          ) : null}
        </nav>

        <div className="mt-auto border-t border-ink-200 px-4 py-3">
          {project.data ? (
            <p className="mb-2">
              {project.data.aiPolicy.localOnly ? (
                <Badge tone="good" icon="🔒">{t('localOnly')}</Badge>
              ) : (
                <Badge tone="warning" icon="☁">{t('cloudAllowed')}</Badge>
              )}
            </p>
          ) : null}
          {user?.globalRoles.includes('superuser') ? (
            <p className="mb-1"><Badge tone="info" icon="★">Platform owner</Badge></p>
          ) : null}
          <p className="truncate text-xs text-ink-600">{user?.displayName}</p>
          <p className="truncate text-xs text-ink-500" title={user?.email}>{user?.email}</p>
          <div className="mt-2 flex items-center justify-between gap-2">
            <button type="button" className="btn-ghost px-0 text-xs" onClick={signOut}>
              {t('signOut')}
            </button>
            <ThemeToggle />
          </div>
        </div>
        </div>
      </aside>

      <main id="main-content" ref={mainRef} tabIndex={-1} className="min-w-0 flex-1 p-4 outline-none sm:p-6">
        <Outlet />
      </main>
    </div>
  )
}

function navClass({ isActive }: { isActive: boolean }) {
  return `flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm transition ${
    isActive ? 'bg-brand-50 font-medium text-brand-800' : 'text-ink-600 hover:bg-ink-100'
  }`
}
