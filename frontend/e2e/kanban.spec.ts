/** Moving cards on the planning board changes their execution status. */
import { expect, test, type Page } from '@playwright/test'

const LEAD = { email: 'lead@company.local', password: 'Analyst!2026' }

async function openBoard(page: Page) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(LEAD.email)
  await page.getByLabel('Password').fill(LEAD.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.getByRole('link', { name: /PORTAL/ }).first().click()
  await page.getByRole('link', { name: 'Planning', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Backlog' })).toBeVisible()
}

const column = (page: Page, name: string) => page.getByRole('region', { name })

const cardIn = (page: Page, columnName: string, stableId: string) =>
  column(page, columnName).getByRole('listitem').filter({ hasText: stableId })

async function moveWithMenu(page: Page, from: string, stableId: string, to: string) {
  await cardIn(page, from, stableId)
    .getByRole('button', { name: `Move ${stableId} to another column` }).click()
  const done = page.waitForResponse((r) => r.url().endsWith('/board/move') && r.ok())
  await cardIn(page, from, stableId).getByRole('button', { name: to, exact: true }).click()
  await done
}

test('a card dragged to another column keeps its new status', async ({ page }) => {
  await openBoard(page)
  // Pin one card by its id, so the test always drags and restores the same one.
  const stableId = (await column(page, 'Backlog').getByRole('listitem').first()
    .locator('p').first().innerText()).trim()
  expect(stableId).toMatch(/^[A-Z]+-\d+$/)

  try {
    const moved = page.waitForResponse((r) => r.url().endsWith('/board/move') && r.ok())
    // Drop near the top of the column: aiming at the centre of a tall column
    // makes Playwright scroll mid drag, which starts the drag on another card.
    await cardIn(page, 'Backlog', stableId).dragTo(column(page, 'Ready'),
                                                   { targetPosition: { x: 40, y: 40 } })
    const body = await (await moved).json()
    expect(body.item.stableId).toBe(stableId)
    expect(body.item.executionStatus).toBe('ready')
    await expect(cardIn(page, 'Ready', stableId)).toBeVisible()
    await expect(page.getByRole('status').filter({ hasText: `${stableId} moved to Ready` }))
      .toBeAttached()

    // Stored on the server, not only on screen.
    await page.reload()
    await expect(cardIn(page, 'Ready', stableId)).toBeVisible()
    await expect(cardIn(page, 'Backlog', stableId)).toHaveCount(0)

    // Back with the keyboard menu; focus stays on the card in its new column.
    await moveWithMenu(page, 'Ready', stableId, 'Backlog')
    await expect(cardIn(page, 'Backlog', stableId)).toBeVisible()
    await expect(column(page, 'Backlog')
      .getByRole('button', { name: `Move ${stableId} to another column` })).toBeFocused()
  } finally {
    // Whatever failed, leave the seeded board as it was.
    await page.reload()
    for (const name of ['Ready', 'In progress', 'Blocked', 'In review', 'Done']) {
      if (await cardIn(page, name, stableId).count()) {
        await moveWithMenu(page, name, stableId, 'Backlog')
      }
    }
  }
})

test('blocking a card records why, and moving it on clears it', async ({ page }) => {
  await openBoard(page)
  await expect(column(page, 'Blocked')).toBeVisible()
  const stableId = (await column(page, 'Backlog').getByRole('listitem').first()
    .locator('p').first().innerText()).trim()
  const reason = 'Waiting for the client SSO metadata'

  try {
    await cardIn(page, 'Backlog', stableId)
      .getByRole('button', { name: `Move ${stableId} to another column` }).click()
    await cardIn(page, 'Backlog', stableId).getByRole('button', { name: 'Blocked', exact: true })
      .click()
    const dialog = page.getByRole('dialog', { name: `Block ${stableId}` })
    await dialog.getByLabel('What is it blocked by?').fill(reason)
    const moved = page.waitForResponse((r) => r.url().endsWith('/board/move') && r.ok())
    await dialog.getByRole('button', { name: 'Move to Blocked' }).click()
    expect((await (await moved).json()).item.executionStatus).toBe('blocked')

    await page.reload()
    await expect(cardIn(page, 'Blocked', stableId).getByText(reason)).toBeVisible()

    await moveWithMenu(page, 'Blocked', stableId, 'Backlog')
    await expect(cardIn(page, 'Backlog', stableId)).toBeVisible()
    await expect(cardIn(page, 'Backlog', stableId).getByText(reason)).toHaveCount(0)
  } finally {
    await page.reload()
    for (const name of ['Ready', 'In progress', 'Blocked', 'In review', 'Done']) {
      if (await cardIn(page, name, stableId).count()) {
        await moveWithMenu(page, name, stableId, 'Backlog')
      }
    }
  }
})
