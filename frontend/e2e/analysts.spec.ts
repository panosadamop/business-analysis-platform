/** A project's AI analysts are chosen in the project setup and used by the next run. */
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }

async function signIn(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(LEAD.email)
  await page.getByLabel('Password').fill(LEAD.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
}

async function openSetup(page: Page) {
  await page.goto('/')
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await page.getByRole('link', { name: 'Project setup', exact: true }).click()
  await page.getByRole('tab', { name: /Analysts/ }).click()
}

async function save(page: Page) {
  const saved = page.waitForResponse((response) =>
    response.request().method() === 'PATCH' && response.ok())
  await page.getByRole('button', { name: 'Save' }).click()
  await saved
}

const ANALYST_NAMES = ['Business analyst', 'UX analyst', 'Data analyst',
  'Technical analyst', 'QA analyst']

/** Ticks exactly the named analysts (in any state the project was left in). */
async function choose(page: Page, names: string[]) {
  // Tick first, then untick, so the picker never refuses the last one.
  for (const name of names) await page.getByRole('checkbox', { name: new RegExp(name) }).check()
  for (const name of ANALYST_NAMES.filter((n) => !names.includes(n))) {
    await page.getByRole('checkbox', { name: new RegExp(name) }).uncheck()
  }
}

test('the analysts are chosen per project and shown before a run', async ({ page }) => {
  await signIn(page)
  await openSetup(page)
  // Remember the project's own choice so the test leaves it exactly as found.
  const original: string[] = []
  for (const name of ANALYST_NAMES) {
    if (await page.getByRole('checkbox', { name: new RegExp(name) }).isChecked()) {
      original.push(name)
    }
  }

  try {
    await choose(page, ['Business analyst', 'UX analyst', 'Technical analyst'])
    // The quality gate needs tests, which only the QA analyst generates.
    await expect(page.getByText(/require tests for stories/)).toBeVisible()
    await save(page)

    await page.getByRole('link', { name: 'Analysis', exact: true }).click()
    await expect(page.getByText('Business analyst → UX analyst → Technical analyst',
                                { exact: true })).toBeVisible()

    // The choice is stored with the project, not only on screen.
    await page.reload()
    await expect(page.getByText('Business analyst → UX analyst → Technical analyst',
                                { exact: true })).toBeVisible()
  } finally {
    await openSetup(page)
    await choose(page, original)
    await save(page)
  }
  await page.getByRole('link', { name: 'Analysis', exact: true }).click()
  await expect(page.getByText(original.join(' → '), { exact: true })).toBeVisible()
})
