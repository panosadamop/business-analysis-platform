/**
 * Automated WCAG 2.1 AA scan of every screen with axe-core.
 *
 * Runs against a seeded deployment like the other browser suites. Each screen is
 * scanned once it has finished loading, plus the states a page alone does not
 * show: an open dialog, a second tab, the Greek interface and the client side.
 * The whole scan runs twice, in the light and the dark theme.
 *
 * Automated rules find roughly a third of WCAG issues; the rest (reading order,
 * meaningful names, zoom and screen reader behaviour) still need a manual pass.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }
const OWNER = { email: 'owner@company.local', password: 'Analyst!2026' }
const CLIENT = { email: 'client@client.local', password: 'Analyst!2026' }

const WCAG_21_AA = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']

/** The project workspaces, by their navigation label and the heading they show. */
const WORKSPACES: { nav: string; heading: string | RegExp }[] = [
  { nav: 'Project setup', heading: 'Project setup' },
  { nav: 'Evidence', heading: 'Evidence workspace' },
  { nav: 'Analysis', heading: 'Analysis workspace' },
  { nav: 'Backlog', heading: 'Backlog' },
  { nav: 'Specifications', heading: /Specification/ },
  { nav: 'Approval inbox', heading: /Approval/ },
  { nav: 'Planning', heading: /Planning/ },
  { nav: 'Testbook', heading: /Testbook/ },
  { nav: 'Dashboards', heading: /dashboards/i },
  { nav: 'Report builder', heading: /Report/ },
  { nav: 'Integrations', heading: /Integration/ },
  { nav: 'Client workspace', heading: /Client|Shar/ },
]

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email)
  await page.getByLabel('Password').fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function openProject(page: Page) {
  await signIn(page, LEAD)
  await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/evidence/)
}

/** Waits until no loading indicator remains, so the scan sees the real content. */
async function settle(page: Page) {
  await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0)
}

/** Scans the page (or one part of it) and fails with a readable list of violations. */
async function expectNoViolations(page: Page, label: string, include?: string) {
  await settle(page)
  let builder = new AxeBuilder({ page }).withTags(WCAG_21_AA)
  if (include) builder = builder.include(include)
  const { violations } = await builder.analyze()

  const report = violations.map((violation) => [
    `[${violation.impact}] ${violation.id}: ${violation.help}`,
    `  ${violation.helpUrl}`,
    ...violation.nodes.slice(0, 5).map((node) =>
      `  - ${node.target.join(' ')}\n    ${node.failureSummary?.split('\n').join('\n    ')}`),
    violation.nodes.length > 5 ? `  … and ${violation.nodes.length - 5} more` : '',
  ].filter(Boolean).join('\n')).join('\n\n')

  expect(violations, `${label}: WCAG 2.1 AA violations\n\n${report}`).toEqual([])
}

// Every screen is scanned in both themes: dark mode has its own contrast pairs.
for (const scheme of ['light', 'dark'] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme })

    test.describe(`accessibility (${scheme}): public screens`, () => {
      test('sign in', async ({ page }) => {
        await page.goto('/login')
        await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
        await expectNoViolations(page, 'Sign in')
      })

      test('sign in with an error shown', async ({ page }) => {
        await signIn(page, { email: LEAD.email, password: 'wrong' })
        await expect(page.getByRole('alert')).toBeVisible()
        await expectNoViolations(page, 'Sign in error')
      })
    })

    test.describe(`accessibility (${scheme}): analyst screens`, () => {
      test('project portfolio', async ({ page }) => {
        await signIn(page, LEAD)
        await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
        await expectNoViolations(page, 'Project portfolio')
      })

      for (const workspace of WORKSPACES) {
        test(`workspace: ${workspace.nav}`, async ({ page }) => {
          await openProject(page)
          await page.getByRole('link', { name: workspace.nav, exact: true }).click()
          await expect(page.getByRole('heading', { level: 1, name: workspace.heading }))
            .toBeVisible()
          await expectNoViolations(page, workspace.nav)
        })
      }

      test('every tab of a tabbed workspace', async ({ page }) => {
        await openProject(page)
        await page.getByRole('link', { name: 'Testbook', exact: true }).click()
        const tabs = page.getByRole('tab')
        const count = await tabs.count()
        for (let index = 0; index < count; index += 1) {
          await tabs.nth(index).click()
          await expectNoViolations(page, `Testbook tab ${index + 1}`)
        }
      })

      test('an open dialog', async ({ page }) => {
        await openProject(page)
        await page.getByRole('link', { name: 'Backlog', exact: true }).click()
        await page.getByRole('button', { name: /^EPIC-001/ }).click()
        await expect(page.getByRole('dialog')).toBeVisible()
        await expectNoViolations(page, 'Backlog item dialog', '[role="dialog"]')
      })

      test('the Greek interface', async ({ page }) => {
        await signIn(page, LEAD)
        await page.getByRole('button', { name: 'Ελληνικά' }).click()
        await expect(page.locator('html')).toHaveAttribute('lang', 'el')
        await expectNoViolations(page, 'Portfolio in Greek')
        await page.getByRole('button', { name: 'English' }).click()
      })
    })

    test.describe(`accessibility (${scheme}): other roles`, () => {
      test('administration', async ({ page }) => {
        await signIn(page, OWNER)
        await page.getByRole('link', { name: 'Administration' }).click()
        await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible()
        await expectNoViolations(page, 'Administration')
      })

      test('client workspace', async ({ page }) => {
        await signIn(page, CLIENT)
        await expect(page).toHaveURL(/\/client/)
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
        await expectNoViolations(page, 'Client workspace')
      })
    })
  })
}
