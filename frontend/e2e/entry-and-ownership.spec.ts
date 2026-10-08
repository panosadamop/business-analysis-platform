/**
 * Authoring entries by hand, charting a report, and the platform owner.
 *
 * Runs against a seeded deployment. Each test creates its own entry with a
 * unique name so repeated runs stay independent.
 */
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }
const OWNER = { email: 'owner@company.local', password: 'Analyst!2026' }

const stamp = () => Date.now().toString().slice(-6)

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(who.email)
  await page.getByLabel('Password').fill(who.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

async function openWorkspace(page: Page, who: typeof LEAD, workspace: string) {
  await signIn(page, who)
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await expect(page).toHaveURL(/\/projects\/[^/]+\/evidence/)
  if (workspace !== 'Evidence') {
    await page.getByRole('link', { name: workspace, exact: true }).click()
  }
}

test.describe('authoring entries by hand', () => {
  test('a requirement is written and appears with its provenance', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Analysis')
    const title = `Hand written requirement ${stamp()}`

    await page.getByRole('button', { name: 'Add requirement' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add a requirement' })
    await dialog.getByLabel('Title').fill(title)
    await dialog.getByLabel(/Statement/).fill('Inactive accounts are refused access.')
    await dialog.getByLabel('Type').selectOption('business_rule')
    await dialog.getByLabel(/Provenance/).selectOption('assumption')
    await dialog.getByRole('button', { name: 'Add requirement' }).click()
    await expect(dialog).toBeHidden()

    await page.getByRole('tab', { name: /Requirements/ }).click()
    const row = page.getByRole('row').filter({ hasText: title })
    await expect(row).toBeVisible()
    await expect(row.getByText('analyst assumption')).toBeVisible()
  })

  test('a question is raised and can be answered', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Analysis')
    const title = `Who signs this off ${stamp()}`

    await page.getByRole('button', { name: 'Add question' }).click()
    const dialog = page.getByRole('dialog', { name: 'Raise a question' })
    await dialog.getByLabel('Question', { exact: true }).fill(title)
    await dialog.getByLabel('Detail').fill('The brief does not name an approver.')
    await dialog.getByLabel(/Severity/).selectOption('major')
    await dialog.getByRole('button', { name: 'Raise question' }).click()
    await expect(dialog).toBeHidden()

    await page.getByRole('tab', { name: /Questions/ }).click()
    const article = page.locator('article', { hasText: title }).first()
    await expect(article).toBeVisible()

    await article.getByPlaceholder(/Record the decision/).fill('The delivery manager.')
    await article.getByRole('button', { name: 'Record answer' }).click()
    await expect(article.getByText('The delivery manager.')).toBeVisible()
  })

  test('a glossary term is added with its Greek wording and removed again',
       async ({ page }) => {
    await openWorkspace(page, LEAD, 'Analysis')
    const term = `Invoice ${stamp()}`

    await page.getByRole('button', { name: 'Add glossary term' }).click()
    const dialog = page.getByRole('dialog', { name: 'Add a glossary term' })
    await dialog.getByLabel('Term', { exact: true }).fill(term)
    await dialog.getByLabel('Definition').fill('A monthly billing document.')
    await dialog.getByLabel(/Greek wording/).fill('Τιμολόγιο')
    await dialog.getByRole('button', { name: 'Add term' }).click()
    await expect(dialog).toBeHidden()

    await page.getByRole('tab', { name: /Glossary/ }).click()
    const row = page.getByRole('row').filter({ hasText: term })
    await expect(row).toBeVisible()
    await expect(row.getByText(/el: Τιμολόγιο/)).toBeVisible()

    await row.getByRole('button', { name: 'Remove' }).click()
    await expect(page.getByRole('row').filter({ hasText: term })).toHaveCount(0)
  })

  test('a specification is written by hand and shown as a draft', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Specifications')
    const title = `Invoice list behaviour ${stamp()}`

    await page.getByRole('button', { name: 'Write a specification' }).click()
    const dialog = page.getByRole('dialog', { name: 'Write a specification' })
    await dialog.getByLabel('Title').fill(title)
    await dialog.getByLabel(/Body/).fill('## Scope\n\nThe list shows 24 months.')
    await dialog.getByRole('button', { name: 'Create specification' }).click()
    await expect(dialog).toBeHidden()

    const section = page.locator('section', { hasText: title }).first()
    await expect(section).toBeVisible()
    await expect(section.getByText('draft')).toBeVisible()
    await expect(section.getByText(/The list shows 24 months/)).toBeVisible()
  })

  test('a process diagram is written as Mermaid source', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Specifications')
    const title = `Sign in flow ${stamp()}`

    await page.getByRole('button', { name: 'Write a specification' }).click()
    const dialog = page.getByRole('dialog', { name: 'Write a specification' })
    await dialog.getByLabel('Kind').selectOption('process_diagram')
    await dialog.getByLabel('Title').fill(title)
    await dialog.getByLabel(/Mermaid source/).fill('flowchart TD\n  start-->done')
    await dialog.getByRole('button', { name: 'Create specification' }).click()
    await expect(dialog).toBeHidden()

    await expect(page.getByText('flowchart TD').first()).toBeVisible()
  })

  test('a test case is written with Gherkin and invalid Gherkin is refused',
       async ({ page }) => {
    await openWorkspace(page, LEAD, 'Testbook')
    const title = `Inactive account refused ${stamp()}`

    await page.getByRole('button', { name: 'Write a test case' }).click()
    const dialog = page.getByRole('dialog', { name: 'Write a test case' })
    await dialog.getByLabel('Title').fill(title)
    await dialog.getByLabel(/Gherkin/).fill('Scenario: no feature keyword')
    await dialog.getByRole('button', { name: 'Create test case' }).click()

    // The dialog stays open and reports why the document was refused.
    await expect(dialog.getByRole('alert')).toContainText('Gherkin')

    await dialog.getByLabel(/Gherkin/).fill(
      '@negative\nFeature: Invoice access\n  Scenario: Inactive account\n'
      + '    Given an inactive customer account\n'
      + '    When the invoice list is opened\n'
      + '    Then access is refused')
    await dialog.getByRole('button', { name: 'Create test case' }).click()
    await expect(dialog).toBeHidden()

    await expect(page.getByRole('row').filter({ hasText: title })).toBeVisible()
  })

  test('a sprint and a milestone are added from the planning workspace',
       async ({ page }) => {
    await openWorkspace(page, LEAD, 'Planning')
    const sprint = `Sprint ${stamp()}`

    await page.getByRole('button', { name: 'Add sprint' }).first().click()
    const sprintDialog = page.getByRole('dialog', { name: 'Add a sprint' })
    await sprintDialog.getByLabel('Name').fill(sprint)
    await sprintDialog.getByLabel('Start date').fill('2026-04-06')
    await sprintDialog.getByLabel('End date').fill('2026-04-17')
    await sprintDialog.getByRole('button', { name: 'Add sprint' }).click()
    await expect(sprintDialog).toBeHidden()

    await page.getByRole('tab', { name: /Sprints/ }).click()
    await expect(page.getByRole('row').filter({ hasText: sprint })).toBeVisible()

    const milestone = `Release ${stamp()}`
    await page.getByRole('button', { name: 'Add milestone' }).first().click()
    const milestoneDialog = page.getByRole('dialog', { name: 'Add a milestone' })
    await milestoneDialog.getByLabel('Name').fill(milestone)
    await milestoneDialog.getByLabel('Due date').fill('2026-08-01')
    await milestoneDialog.getByRole('button', { name: 'Add milestone' }).click()
    await expect(milestoneDialog).toBeHidden()

    await page.getByRole('tab', { name: /Milestones/ }).click()
    await expect(page.getByRole('row').filter({ hasText: milestone })).toBeVisible()
  })

  test('evidence is linked to a backlog item by hand', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Backlog')
    await page.getByRole('button', { name: /^EPIC-001/ }).click()

    const drawer = page.getByRole('dialog')
    await drawer.getByRole('button', { name: 'Link evidence' }).click()

    const dialog = page.getByRole('dialog', { name: /Link evidence to/ })
    await dialog.getByLabel('Source').selectOption({ index: 1 })
    await dialog.getByLabel(/Locator value/).fill('Scope#p2')
    await dialog.getByLabel('Rationale').fill('States the rule directly')
    await dialog.getByRole('button', { name: 'Link evidence' }).click()
    await expect(dialog).toBeHidden()
  })
})

test.describe('charting a report', () => {
  test('a previewed report is charted and the values stay available', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Report builder')

    await page.getByRole('button', { name: 'Preview', exact: true }).click()
    await expect(page.getByText(/snapshot snap-/)).toBeVisible()

    await page.getByLabel('View').selectOption('bar')
    await page.getByLabel('Group by').selectOption('type')
    await page.getByLabel('Measure').selectOption('effortHours')

    const chart = page.locator('section.viz-root').filter({ hasText: /by Type/ })
    await expect(chart).toBeVisible()
    await expect(chart.getByText(/Definition\./)).toBeVisible()
    await expect(chart.locator('svg')).toBeVisible()

    await chart.getByRole('button', { name: 'Show values' }).click()
    await expect(chart.getByRole('table')).toBeVisible()
  })

  test('counting rows needs no measure', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Report builder')
    await page.getByRole('button', { name: 'Preview', exact: true }).click()
    await expect(page.getByText(/snapshot snap-/)).toBeVisible()

    await page.getByLabel('View').selectOption('bar')
    await page.getByLabel('Group by').selectOption('state')
    await page.getByLabel('Aggregation').selectOption('count')

    await expect(page.getByLabel('Measure')).toBeDisabled()
    await expect(page.locator('section.viz-root')
  .filter({ hasText: /Count by/ })).toBeVisible()
  })

  test('a report definition is saved and reloaded', async ({ page }) => {
    await openWorkspace(page, LEAD, 'Report builder')
    const name = `Saved report ${stamp()}`

    await page.getByRole('button', { name: 'Save', exact: true }).first().click()
    await page.getByPlaceholder('Name this report').fill(name)
    await page.getByRole('button', { name: 'Save', exact: true }).last().click()

    await expect(page.getByLabel('Saved reports')).toBeVisible()
    await page.getByLabel('Saved reports').selectOption({ label: name })
  })
})

test.describe('the platform owner', () => {
  test('sees every project without being a member of any', async ({ page }) => {
    await signIn(page, OWNER)
    await expect(page.getByRole('heading', { name: 'Project portfolio' })).toBeVisible()
    await expect(page.getByRole('link', { name: /PORTAL/ }).first()).toBeVisible()
  })

  test('reaches the internal workspaces and the cost figures', async ({ page }) => {
    await openWorkspace(page, OWNER, 'Backlog')
    await expect(page.getByRole('heading', { name: 'Backlog' })).toBeVisible()

    await page.getByRole('link', { name: 'Dashboards', exact: true }).click()
    await expect(page.getByText('Cost and budget comparison')).toBeVisible()
  })

  test('administers the deployment', async ({ page }) => {
    await signIn(page, OWNER)
    await page.getByRole('link', { name: 'Administration' }).click()
    await expect(page.getByRole('heading', { name: 'Administration' })).toBeVisible()
    await expect(page.getByText(/Deterministic local analyst|local/).first()).toBeVisible()

    await page.getByRole('tab', { name: /Accounts/ }).click()
    await expect(page.getByRole('row').filter({ hasText: 'owner@company.local' })).toBeVisible()
    await expect(page.getByRole('row').filter({ hasText: 'owner@company.local' })
      .getByText('superuser')).toBeVisible()
  })
})
