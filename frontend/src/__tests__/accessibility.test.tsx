/** Keyboard and assistive technology behaviour of the shared primitives (WCAG 2.1 AA). */
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ThemeToggle } from '../components/ThemeToggle'
import { CreateModal, Field, Modal, PageHeader, Table, Tabs } from '../components/ui'
import { I18nProvider } from '../i18n'
import { THEME_STORAGE_KEY } from '../lib/theme'

function ModalHarness() {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>Open dialog</button>
      <Modal open={open} title="Item detail" onClose={() => setOpen(false)}
             footer={<button type="button">Done</button>}>
        <input aria-label="Note" />
      </Modal>
    </div>
  )
}

describe('dialogs', () => {
  it('is named by its heading and moves focus inside when opened', async () => {
    render(<ModalHarness />)
    await userEvent.click(screen.getByRole('button', { name: 'Open dialog' }))
    expect(screen.getByRole('dialog', { name: 'Item detail' })).toBeInTheDocument()
    expect(screen.getByLabelText('Note')).toHaveFocus()
  })

  it('keeps Tab inside the dialog and returns focus to the opener on Escape', async () => {
    render(<ModalHarness />)
    const opener = screen.getByRole('button', { name: 'Open dialog' })
    await userEvent.click(opener)

    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus()
    await userEvent.tab()
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus()
    await userEvent.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('closes a create dialog with Escape', async () => {
    const onClose = vi.fn()
    render(<CreateModal open title="New risk" onClose={onClose} onSubmit={() => {}}>
      <input aria-label="Title" />
    </CreateModal>)
    expect(screen.getByRole('dialog', { name: 'New risk' })).toBeInTheDocument()
    expect(screen.getByLabelText('Title')).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})

describe('tabs', () => {
  it('moves between tabs with the arrow, Home and End keys', async () => {
    function Harness() {
      const [active, setActive] = useState('a')
      return <Tabs active={active} onChange={setActive} tabs={[
        { key: 'a', label: 'Alpha' }, { key: 'b', label: 'Beta' }, { key: 'c', label: 'Gamma' },
      ]} />
    }
    render(<Harness />)
    const alpha = screen.getByRole('tab', { name: 'Alpha' })
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute('tabindex', '-1')

    alpha.focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Beta' })).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{End}')
    expect(screen.getByRole('tab', { name: 'Gamma' })).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    expect(alpha).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}')
    expect(screen.getByRole('tab', { name: 'Gamma' })).toHaveFocus()
  })
})

describe('tables', () => {
  it('opens a clickable row from the keyboard', async () => {
    const onRowClick = vi.fn()
    render(<Table rows={[{ id: 'r1', name: 'Invoice list' }]} rowKey={(row) => row.id}
                  onRowClick={onRowClick}
                  columns={[{ key: 'name', header: 'Name', render: (row) => row.name }]} />)
    await userEvent.tab()
    expect(screen.getByRole('row', { name: /Invoice list/ })).toHaveFocus()
    await userEvent.keyboard('{Enter}')
    expect(onRowClick).toHaveBeenCalledWith({ id: 'r1', name: 'Invoice list' })
  })
})

describe('fields and pages', () => {
  it('describes a control by its hint without folding it into the name', () => {
    render(<Field label="Budget" hint="In euro, excluding VAT"><input /></Field>)
    const input = screen.getByRole('textbox', { name: 'Budget' })
    expect(input).toHaveAccessibleDescription('In euro, excluding VAT')
  })

  it('gives each screen a descriptive document title', () => {
    render(<PageHeader title="Backlog" />)
    expect(document.title).toBe('Backlog · AI Analysis Team')
  })
})

describe('theme toggle', () => {
  it('offers system, light and dark, and applies and stores the choice', async () => {
    render(<I18nProvider><ThemeToggle /></I18nProvider>)
    expect(screen.getByRole('group', { name: 'Theme' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Dark' }))
    expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute('aria-pressed', 'true')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')

    await userEvent.click(screen.getByRole('button', { name: 'Match system' }))
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  })
})
