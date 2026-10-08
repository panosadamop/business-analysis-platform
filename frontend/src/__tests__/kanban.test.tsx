/** Moving cards on the Kanban board: drag and drop, the Move to menu, rollback. */
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { KanbanBoard } from '../components/KanbanBoard'
import { tokenStore } from '../lib/api'
import type { BoardState } from '../types'

const CARD = {
  id: 'i1', stableId: 'STORY-001', title: 'Customer registers', rev: 3,
  executionStatus: 'not_started', priority: 'high' as const, state: 'draft',
  blockedReason: null, approvedVersion: null,
}

function boardWith(columnKey: string, rev = 3, blockedReason: string | null = null): BoardState {
  const columns = [
    { key: 'backlog', name: 'Backlog', wipLimit: null, mapsToStatus: 'not_started' },
    { key: 'in_progress', name: 'In progress', wipLimit: 5, mapsToStatus: 'in_progress' },
    { key: 'blocked', name: 'Blocked', wipLimit: null, mapsToStatus: 'blocked' },
    { key: 'done', name: 'Done', wipLimit: null, mapsToStatus: 'done' },
  ]
  return {
    note: 'Execution status is tracked separately from artifact approval.',
    columns: columns.map((column) => {
      const items = column.key === columnKey ? [{ ...CARD, rev, blockedReason }] : []
      return { ...column, count: items.length, overLimit: false, items }
    }),
  }
}

function BoardFromCache() {
  // Reads the board the way the planning page does; the cache is pre-filled.
  const { data } = useQuery<BoardState>({
    queryKey: ['board-state', 'p1'], queryFn: () => new Promise<BoardState>(() => {}),
    staleTime: Infinity,
  })
  return data ? <KanbanBoard projectId="p1" board={data} /> : null
}

function renderBoard(board: BoardState) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['board-state', 'p1'], board)
  render(<QueryClientProvider client={client}><BoardFromCache /></QueryClientProvider>)
  return client
}

function column(name: string) {
  return screen.getByRole('region', { name })
}

function stubMove(response: () => Response) {
  const fetchMock = vi.fn(async () => response())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => tokenStore.set('test-token'))
afterEach(() => vi.unstubAllGlobals())

describe('kanban board', () => {
  it('moves a card with the Move to menu and announces it', async () => {
    const fetchMock = stubMove(() => new Response(JSON.stringify({
      item: { id: 'i1', stableId: 'STORY-001', rev: 4, executionStatus: 'in_progress' },
      column: 'in_progress', warning: null, board: boardWith('in_progress', 4),
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderBoard(boardWith('backlog'))

    await userEvent.click(within(column('Backlog'))
      .getByRole('button', { name: 'Move STORY-001 to another column' }))
    await userEvent.click(screen.getByRole('button', { name: 'In progress' }))

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toEqual(
      { itemId: 'i1', columnKey: 'in_progress', expectedRev: 3 })
    await waitFor(() => expect(within(column('In progress'))
      .getByText('Customer registers')).toBeInTheDocument())
    expect(within(column('Backlog')).queryByText('Customer registers')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('STORY-001 moved to In progress.')
    // Focus follows the card so a keyboard user can keep moving it.
    expect(within(column('In progress'))
      .getByRole('button', { name: 'Move STORY-001 to another column' })).toHaveFocus()
  })

  it('puts the card back when the server refuses the move', async () => {
    stubMove(() => new Response(JSON.stringify({ error: {
      code: 'version_conflict', message: 'The item changed since you loaded it' } }),
    { status: 409 }))
    renderBoard(boardWith('backlog'))

    await userEvent.click(screen.getByRole('button', { name: /Move STORY-001/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('changed since you loaded it')
    expect(within(column('Backlog')).getByText('Customer registers')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('could not be moved')
  })

  it('moves a card dropped on another column', async () => {
    const fetchMock = stubMove(() => new Response(JSON.stringify({
      item: { id: 'i1', stableId: 'STORY-001', rev: 4, executionStatus: 'done' },
      column: 'done', warning: null, board: boardWith('done', 4),
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderBoard(boardWith('backlog'))

    const store = new Map<string, string>()
    const dataTransfer = {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? '',
      effectAllowed: 'all', dropEffect: 'none',
    }
    const card = within(column('Backlog')).getByText('Customer registers').closest('li')!
    fireEvent.dragStart(card, { dataTransfer })
    fireEvent.dragOver(column('Done'), { dataTransfer })
    fireEvent.drop(column('Done'), { dataTransfer })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(within(column('Done'))
      .getByText('Customer registers')).toBeInTheDocument())
  })

  it('shows the WIP limit warning the server reports', async () => {
    stubMove(() => new Response(JSON.stringify({
      item: { id: 'i1', stableId: 'STORY-001', rev: 4, executionStatus: 'in_progress' },
      column: 'in_progress', warning: 'In progress is over its WIP limit of 0',
      board: boardWith('in_progress', 4),
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderBoard(boardWith('backlog'))

    await userEvent.click(screen.getByRole('button', { name: /Move STORY-001/ }))
    await userEvent.click(screen.getByRole('button', { name: 'In progress' }))

    expect(await screen.findByText('In progress is over its WIP limit of 0.'))
      .toBeInTheDocument()
  })

  it('asks what a card is blocked by before moving it to Blocked', async () => {
    const fetchMock = stubMove(() => new Response(JSON.stringify({
      item: { id: 'i1', stableId: 'STORY-001', rev: 4, executionStatus: 'blocked',
              blockedReason: 'Waiting for SSO metadata' },
      column: 'blocked', warning: null,
      board: boardWith('blocked', 4, 'Waiting for SSO metadata'),
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderBoard(boardWith('backlog'))

    await userEvent.click(screen.getByRole('button', { name: /Move STORY-001/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Blocked' }))

    // Nothing is sent until a reason is given.
    const dialog = screen.getByRole('dialog', { name: 'Block STORY-001' })
    expect(fetchMock).not.toHaveBeenCalled()
    await userEvent.type(within(dialog).getByLabelText('What is it blocked by?'),
                         'Waiting for SSO metadata')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move to Blocked' }))

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(JSON.parse(String(init.body))).toMatchObject(
      { columnKey: 'blocked', blockedReason: 'Waiting for SSO metadata' })
    await waitFor(() => expect(within(column('Blocked'))
      .getByText('Waiting for SSO metadata')).toBeInTheDocument())
  })

  it('leaves the card where it was when blocking is cancelled', async () => {
    const fetchMock = stubMove(() => new Response('{}', { status: 500 }))
    renderBoard(boardWith('backlog'))

    await userEvent.click(screen.getByRole('button', { name: /Move STORY-001/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Blocked' }))
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(within(column('Backlog')).getByText('Customer registers')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('STORY-001 was not moved.')
  })
})
