/** Dark mode: follows the system, can be fixed either way, and is remembered. */
import { expect, test, type Page } from '@playwright/test'

const background = (page: Page) =>
  page.evaluate(() => getComputedStyle(document.body).backgroundColor)

const LIGHT_PAGE = 'rgb(246, 247, 249)'
const DARK_PAGE = 'rgb(14, 17, 23)'

test.describe('with a dark operating system theme', () => {
  test.use({ colorScheme: 'dark' })

  test('follows the system until a theme is chosen', async ({ page }) => {
    await page.goto('/login')
    expect(await background(page)).toBe(DARK_PAGE)
    await expect(page.getByRole('button', { name: 'Match system' }))
      .toHaveAttribute('aria-pressed', 'true')
  })

  test('a light choice overrides the system and survives a reload', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: 'Light' }).click()
    expect(await background(page)).toBe(LIGHT_PAGE)

    await page.reload()
    // Applied by index.html before the application script runs.
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light')
    expect(await background(page)).toBe(LIGHT_PAGE)

    await page.getByRole('button', { name: 'Match system' }).click()
    await expect(page.locator('html')).not.toHaveAttribute('data-theme', /.*/)
    expect(await background(page)).toBe(DARK_PAGE)
  })
})

test.describe('with a light operating system theme', () => {
  test.use({ colorScheme: 'light' })

  test('a dark choice applies before the first paint', async ({ page }) => {
    await page.goto('/login')
    await page.getByRole('button', { name: 'Dark' }).click()
    expect(await background(page)).toBe(DARK_PAGE)

    // The stored theme is on <html> as soon as the document is parsed.
    await page.goto('/login', { waitUntil: 'commit' })
    await page.waitForFunction(() => document.readyState !== 'loading')
    expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe('dark')
  })
})
