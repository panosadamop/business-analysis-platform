/**
 * Phone layouts: every screen reflows at 375px and at 320px (WCAG 1.4.10)
 * without sideways page scrolling, and the navigation folds behind a menu.
 *
 * Wide data tables may scroll inside their own card; only the page itself must
 * never scroll horizontally.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }

const WORKSPACES = ['setup', 'evidence', 'analysis', 'backlog', 'specifications',
  'approvals', 'planning', 'testbook', 'dashboards', 'reports', 'integrations', 'sharing']

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(LEAD.email)
  await page.getByLabel('Password').fill(LEAD.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
}

/** The project's base URL, found through the portfolio. */
async function projectBase(page: Page) {
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/evidence/)
  return page.url().replace(/\/evidence.*/, '')
}

async function expectNoPageOverflow(page: Page, label: string) {
  await expect(page.getByRole('status').filter({ hasText: /Loading/ })).toHaveCount(0)
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow, `${label} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(1)
}

for (const width of [375, 320]) {
  test.describe(`phone at ${width}px`, () => {
    test.use({ viewport: { width, height: 812 }, hasTouch: true, isMobile: true })

    test('every screen reflows without sideways scrolling', async ({ page }) => {
      test.setTimeout(120_000)
      await page.goto('/login')
      await expectNoPageOverflow(page, 'Sign in')
      await signIn(page)
      await expectNoPageOverflow(page, 'Portfolio')
      const base = await projectBase(page)
      for (const slug of WORKSPACES) {
        await page.goto(`${base}/${slug}`)
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
        await expectNoPageOverflow(page, slug)
      }
    })

    test('an item dialog fits the screen', async ({ page }) => {
      await signIn(page)
      const base = await projectBase(page)
      await page.goto(`${base}/backlog`)
      await page.getByRole('button', { name: /^EPIC-001/ }).click()
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      const box = await dialog.boundingBox()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width)
      await expect(dialog.getByRole('button', { name: 'Close' })).toBeInViewport()
    })
  })
}

test.describe('phone navigation', () => {
  test.use({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true })

  test('the screen opens on its content, with navigation behind a menu', async ({ page }) => {
    await signIn(page)
    const base = await projectBase(page)
    const menu = page.getByRole('button', { name: 'Menu' })
    const main = page.getByRole('navigation', { name: 'Main' })

    // The heading is on screen at once; the workspace links are folded away.
    await expect(page.getByRole('heading', { level: 1 })).toBeInViewport()
    await expect(main).toBeHidden()
    await expect(menu).toHaveAttribute('aria-expanded', 'false')

    await menu.click()
    await expect(menu).toHaveAttribute('aria-expanded', 'true')
    await expect(main).toBeVisible()
    const scan = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    expect(scan.violations.map((violation) => violation.id)).toEqual([])

    // Choosing a destination navigates and folds the menu again.
    await main.getByRole('link', { name: 'Backlog', exact: true }).click()
    await expect(page).toHaveURL(`${base}/backlog`)
    await expect(main).toBeHidden()
    await expect(page.getByRole('heading', { level: 1, name: 'Backlog' })).toBeInViewport()

    // Escape closes an open menu and returns focus to its button.
    await menu.click()
    await page.keyboard.press('Escape')
    await expect(main).toBeHidden()
    await expect(menu).toBeFocused()
  })

  test('form fields use a 16px font so iOS does not zoom on focus', async ({ page }) => {
    await page.goto('/login')
    const size = await page.getByLabel('Email').evaluate(
      (element) => getComputedStyle(element).fontSize)
    expect(size).toBe('16px')
  })
})
