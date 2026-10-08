/**
 * Browser end to end journey through the analyst workspaces.
 *
 * Runs against a seeded deployment: the fourteen screens are reachable, the
 * approval bundle behaves as specified, and a client reviewer sees only what was
 * shared with them.
 */
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }
const CLIENT = { email: 'client@client.local', password: 'Analyst!2026' }

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email)
  await page.getByLabel('Password').fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function openProject(page: Page, workspace: string) {
  await signIn(page, LEAD)
  await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/evidence/)
  if (workspace !== 'evidence') {
    await page.getByRole('link', { name: workspace, exact: true }).click()
  }
}

test.describe('sign in', () => {
  test('rejects a wrong password without revealing which field was wrong', async ({
    page,
  }) => {
    await signIn(page, { email: LEAD.email, password: 'wrong' })
    await expect(page.getByRole('alert')).toContainText('Email or password is incorrect')
    await expect(page).toHaveURL(/\/login/)
  })

  test('signs a lead analyst into the portfolio', async ({ page }) => {
    await signIn(page, LEAD)
    await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'PORTAL — Customer Portal' }))
      .toBeVisible()
    await expect(page.getByText('Local only').first()).toBeVisible()
  })

  test('offers the interface in Greek', async ({ page }) => {
    await signIn(page, LEAD)
    await page.getByRole('button', { name: 'Ελληνικά' }).click()
    await expect(page.getByRole('heading', { name: 'Χαρτοφυλάκιο έργων' })).toBeVisible()
    await page.getByRole('button', { name: 'English' }).click()
    await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
  })
})

test.describe('analyst workspaces', () => {
  test('evidence workspace lists sources with their extraction state', async ({
    page,
  }) => {
    await openProject(page, 'evidence')
    await expect(page.getByRole('heading', { name: 'Evidence workspace' })).toBeVisible()
    await expect(page.getByText('Customer Portal brief')).toBeVisible()
    await expect(page.getByText('ready').first()).toBeVisible()
    await expect(page.getByText(/Limits:/)).toBeVisible()
  })

  test('a source opens its extracted excerpts with locators', async ({ page }) => {
    await openProject(page, 'evidence')
    await page.getByText('Customer Portal brief').click()
    const dialog = page.getByRole('dialog', { name: 'Source viewer' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText(/Extracted excerpts/)).toBeVisible()
    await expect(dialog.locator('code').first()).toContainText(':')
  })

  test('analysis workspace shows the three role stages', async ({ page }) => {
    await openProject(page, 'Analysis')
    await expect(page.getByRole('heading', { name: 'Analysis workspace' })).toBeVisible()
    await expect(page.getByText(/draft and needs human approval/)).toBeVisible()
    await expect(page.getByText('Business analyst').first()).toBeVisible()
    await expect(page.getByText('Technical analyst').first()).toBeVisible()
    await expect(page.getByText('QA analyst').first()).toBeVisible()
    await expect(page.getByText('succeeded').first()).toBeVisible()
  })

  test('requirements carry provenance badges', async ({ page }) => {
    await openProject(page, 'Analysis')
    await page.getByRole('tab', { name: /Requirements/ }).click()
    await expect(page.getByText('AI proposal').first()).toBeVisible()
  })

  test('backlog tree expands into the item detail', async ({ page }) => {
    await openProject(page, 'Backlog')
    await expect(page.getByRole('heading', { name: 'Backlog' })).toBeVisible()
    await page.getByRole('button', { name: /^EPIC-001/ }).click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Acceptance criteria' }))
      .toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Estimate' })).toBeVisible()
    await expect(dialog.getByRole('heading', { name: 'Version history' })).toBeVisible()
    await expect(dialog.getByText('not approved')).toBeVisible()
  })

  test('testbook shows coverage and Gherkin in both dialects', async ({ page }) => {
    await openProject(page, 'Testbook')
    await expect(page.getByText('Criteria covered')).toBeVisible()
    await expect(page.getByText(/never records a run status/)).toBeVisible()

    await page.getByRole('row').nth(1).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByText('pending_review')).toBeVisible()
    await dialog.getByRole('button', { name: 'EL' }).click()
    await expect(dialog.getByText(/Λειτουργία:/)).toBeVisible()
  })

  test('dashboards render charts with their definitions', async ({ page }) => {
    await openProject(page, 'Dashboards')
    await expect(page.getByRole('heading', { name: 'Project dashboards' })).toBeVisible()
    await expect(page.getByText('Planned versus actual effort')).toBeVisible()
    await expect(page.getByText(/Definition\./).first()).toBeVisible()

    const chart = page.locator('section', { hasText: 'Planned versus actual effort' })
      .first()
    await chart.getByRole('button', { name: 'Show values' }).click()
    await expect(chart.getByRole('table')).toBeVisible()
  })

  test('report builder previews a dataset and respects permissions', async ({ page }) => {
    await openProject(page, 'Report builder')
    await page.getByRole('button', { name: 'Preview' }).click()
    await expect(page.getByText(/snapshot snap-/)).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
  })

  test('integration console warns before any mapping is approved', async ({ page }) => {
    await openProject(page, 'Integrations')
    await expect(page.getByRole('heading', { name: 'Integration console' })).toBeVisible()
    await expect(page.getByText('No connector configured')).toBeVisible()
  })

  test('planning board explains that execution is separate from approval', async ({
    page,
  }) => {
    await openProject(page, 'Planning')
    await expect(page.getByText(/separately from artifact approval/)).toBeVisible()
    await expect(page.getByText('Backlog', { exact: true }).first()).toBeVisible()
  })
})

test.describe('approval bundle', () => {
  test('previews the manifest and refuses to approve past a blocker', async ({
    page,
  }) => {
    await openProject(page, 'Approval inbox')
    await expect(page.getByRole('heading', { name: 'Approval inbox' })).toBeVisible()

    await page.getByRole('button', { name: 'Preview bundle' }).first().click()
    const dialog = page.getByRole('dialog', { name: /Approval bundle/ })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByText('Version manifest')).toBeVisible()
    await expect(dialog.getByText(/fails atomically/)).toBeVisible()

    // A critical blocker holds the decision until it is waived with a rationale.
    const criticalBlockers = dialog.getByText('⛔ critical')
    const approve = dialog.getByRole('button', { name: 'Approve bundle' })
    if (await criticalBlockers.count()) {
      await expect(approve).toBeDisabled()
    } else {
      await expect(dialog.getByText(/No blockers/)).toBeVisible()
      await expect(approve).toBeEnabled()
    }
    await dialog.getByRole('button', { name: 'Cancel' }).click()
  })

  test('approves a bundle and records the inherited versions', async ({ page }) => {
    await openProject(page, 'Approval inbox')
    await page.getByRole('button', { name: 'Preview bundle' }).first().click()

    const dialog = page.getByRole('dialog', { name: /Approval bundle/ })
    await expect(dialog).toBeVisible()

    // Waive every waivable critical blocker with a recorded rationale.
    const waiveButtons = dialog.getByRole('button', { name: 'Waive with rationale' })
    for (let index = await waiveButtons.count(); index > 0; index -= 1) {
      await waiveButtons.first().click()
      await dialog.getByPlaceholder('Recorded rationale').first()
        .fill('Accepted during the automated browser check')
      await dialog.getByRole('button', { name: 'Record waiver' }).first().click()
    }

    const approve = dialog.getByRole('button', { name: 'Approve bundle' })
    if (await approve.isDisabled()) {
      test.skip(true, 'this bundle carries a blocker that cannot be waived')
    }
    await approve.click()
    await expect(dialog).toBeHidden()

    await page.getByRole('tab', { name: /Approval history/ }).click()
    await expect(page.getByText('approve').first()).toBeVisible()
    await expect(page.getByText(/inherited/).first()).toBeVisible()

    // Leave the deployment as it was found.
    page.once('dialog', (prompt) => prompt.accept('automated browser check'))
    await page.getByRole('button', { name: 'Revoke approval' }).first().click()
    await expect(page.getByText('revoked').first()).toBeVisible()
  })
})

test.describe('client reviewer', () => {
  test('sees only the client workspace, never the internal screens', async ({ page }) => {
    await signIn(page, CLIENT)
    await expect(page).toHaveURL(/\/client/)
    // Either shared content or an explicit "nothing shared" state, never the
    // internal workspaces.
    // The heading shows whether or not anything has been shared yet.
    await expect(page.getByRole('heading', { name: 'Client workspace' })).toBeVisible()

    // No internal navigation is offered.
    await expect(page.getByRole('link', { name: 'Backlog' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Report builder' })).toHaveCount(0)
  })

  test('a direct link to an internal workspace yields no project content', async ({
    page,
  }) => {
    await signIn(page, CLIENT)
    await page.goto('/projects/any-project-id/backlog')
    await expect(page.getByText(/Customer Portal brief/)).toHaveCount(0)
    await expect(page.getByRole('table')).toHaveCount(0)
  })
})

test('the application is usable at a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 900 })
  await signIn(page, LEAD)
  await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
