/**
 * Kanban board: drag a card to another column, or use its "Move to" menu.
 *
 * Moving a card sets its execution status from the column it lands in. The
 * board updates at once and rolls back if the server refuses the move (a stale
 * revision, or no permission). Dragging needs a pointer, so every card also has
 * a "Move to" menu that works with a keyboard, a screen reader and touch
 * (WCAG 2.1.1); the result of each move is announced.
 *
 * A column that maps to the blocked status asks what the work is waiting on
 * before the card moves there; moving the card out again clears the reason.
 */
import { useEffect, useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../lib/api'
import type { BoardState } from '../types'
import { Badge, CreateModal, ErrorBanner, Field, Note } from './ui'

type Card = BoardState['columns'][number]['items'][number]

interface MoveResult {
  item: { id: string; stableId: string; rev: number; executionStatus: string }
  column: string
  warning: string | null
  board: BoardState
}

const DRAG_TYPE = 'application/x-ait-card'

const isBlocking = (column?: BoardState['columns'][number]) => column?.mapsToStatus === 'blocked'

/** The board with one card moved, as the server will compute it. */
function withCardMoved(board: BoardState, cardId: string, toKey: string,
                       blockedReason: string | null): BoardState {
  let moving: Card | undefined
  const columns = board.columns.map((column) => {
    const items = column.items.filter((card) => {
      if (card.id !== cardId) return true
      moving = card
      return false
    })
    return { ...column, items }
  })
  if (!moving) return board
  return {
    ...board,
    columns: columns.map((column) => {
      const items = column.key === toKey
        ? [...column.items, { ...moving!, blockedReason }] : column.items
      return {
        ...column, items, count: items.length,
        overLimit: column.wipLimit !== null && column.wipLimit !== undefined
          && items.length > column.wipLimit,
      }
    }),
  }
}

export function KanbanBoard({ projectId, board }: { projectId: string; board: BoardState }) {
  const queryClient = useQueryClient()
  const queryKey = ['board-state', projectId]
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [warning, setWarning] = useState<string | null>(null)
  const [menuFor, setMenuFor] = useState<string | null>(null)
  // A move into a blocked column waits here until a reason is given.
  const [pendingBlock, setPendingBlock] = useState<
    { card: Card; fromKey: string; toKey: string; keepFocus: boolean } | null>(null)
  const [reason, setReason] = useState('')
  // Where focus goes after a keyboard move: the card's "Move to" button, once
  // the card shows in that column (its new one, or its old one after a rollback).
  const [focusTarget, setFocusTarget] = useState<{ cardId: string; columnKey: string } | null>(null)
  const boardRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!focusTarget) return
    const button = boardRef.current?.querySelector<HTMLElement>(
      `[data-column="${focusTarget.columnKey}"] [data-move-button="${focusTarget.cardId}"]`)
    if (!button) return
    button.focus()
    setFocusTarget(null)
  }, [focusTarget, board])

  const columnName = (key: string) => board.columns.find((c) => c.key === key)?.name ?? key

  const move = useMutation({
    mutationFn: ({ card, toKey, blockedReason }: {
      card: Card; toKey: string; fromKey: string; blockedReason?: string
    }) =>
      api<MoveResult>(`/projects/${projectId}/board/move`, {
        method: 'POST',
        body: { itemId: card.id, columnKey: toKey, expectedRev: card.rev,
                ...(blockedReason ? { blockedReason } : {}) },
      }),
    onMutate: async ({ card, toKey, blockedReason }) => {
      setWarning(null)
      await queryClient.cancelQueries({ queryKey })
      const previous = queryClient.getQueryData<BoardState>(queryKey)
      if (previous) {
        queryClient.setQueryData(queryKey,
                                 withCardMoved(previous, card.id, toKey, blockedReason ?? null))
      }
      return { previous }
    },
    onError: (_error, { card, fromKey }, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous)
      setFocusTarget((target) => (target ? { cardId: card.id, columnKey: fromKey } : null))
      setAnnouncement(`${card.stableId} could not be moved and is back where it was.`)
      // A refused move may mean the board is out of date; fetch the current one.
      void queryClient.invalidateQueries({ queryKey })
    },
    onSuccess: (result, { card, toKey }) => {
      queryClient.setQueryData(queryKey, result.board)
      setWarning(result.warning)
      setAnnouncement(`${card.stableId} moved to ${columnName(toKey)}.`
        + (result.warning ? ` ${result.warning}.` : ''))
      // Dashboards read the same status changes (cycle time, flow).
      void queryClient.invalidateQueries({ queryKey: ['chart'] })
    },
  })

  function requestMove(card: Card, fromKey: string, toKey: string, { keepFocus = false } = {}) {
    setMenuFor(null)
    if (fromKey === toKey || move.isPending) return
    if (isBlocking(board.columns.find((c) => c.key === toKey))) {
      setReason('')
      setPendingBlock({ card, fromKey, toKey, keepFocus })
      return
    }
    if (keepFocus) setFocusTarget({ cardId: card.id, columnKey: toKey })
    move.mutate({ card, toKey, fromKey })
  }

  function confirmBlock() {
    if (!pendingBlock || !reason.trim()) return
    const { card, fromKey, toKey, keepFocus } = pendingBlock
    setPendingBlock(null)
    if (keepFocus) setFocusTarget({ cardId: card.id, columnKey: toKey })
    move.mutate({ card, toKey, fromKey, blockedReason: reason.trim() })
  }

  function onDrop(event: DragEvent<HTMLElement>, toKey: string) {
    event.preventDefault()
    setOver(null)
    setDragging(null)
    const raw = event.dataTransfer.getData(DRAG_TYPE)
    if (!raw) return
    const { cardId, fromKey } = JSON.parse(raw) as { cardId: string; fromKey: string }
    const card = board.columns.flatMap((c) => c.items).find((c) => c.id === cardId)
    if (card) requestMove(card, fromKey, toKey)
  }

  return (
    <>
      <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
      <p className="mb-3 text-xs text-ink-500">
        Drag a card to another column, or use its <span className="font-medium">Move to</span>{' '}
        menu. The column sets the item&apos;s execution status; approval is not affected.
      </p>
      {move.error ? <div className="mb-3"><ErrorBanner error={move.error} /></div> : null}
      {warning ? <div className="mb-3"><Note tone="warning">{warning}.</Note></div> : null}

      <div ref={boardRef}
           className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {board.columns.map((column) => (
          <section
            key={column.key}
            aria-labelledby={`column-${column.key}`}
            data-column={column.key}
            onDragOver={(event) => {
              if (!dragging) return
              event.preventDefault()
              event.dataTransfer.dropEffect = 'move'
              if (over !== column.key) setOver(column.key)
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(null)
            }}
            onDrop={(event) => onDrop(event, column.key)}
            className={`flex min-h-[8rem] flex-col rounded-lg border transition ${
              over === column.key
                ? 'border-brand-500 bg-brand-50 ring-2 ring-brand-500'
                : 'border-ink-200 bg-ink-50/50'}`}
          >
            <header className="flex items-center justify-between border-b border-ink-200 px-2 py-1.5">
              <h3 id={`column-${column.key}`} className="text-xs font-semibold text-ink-700">
                {column.name}
              </h3>
              <span className={`text-xs tabular-nums ${
                column.overLimit ? 'font-semibold text-red-700' : 'text-ink-500'}`}
                    aria-label={column.wipLimit !== null && column.wipLimit !== undefined
                      ? `${column.count} of a limit of ${column.wipLimit}` : `${column.count} items`}>
                {column.count}{column.wipLimit !== null && column.wipLimit !== undefined
                  ? `/${column.wipLimit}` : ''}
              </span>
            </header>
            {column.overLimit ? (
              <p className="px-2 py-1 text-xs text-red-700">WIP limit exceeded</p>
            ) : null}
            <ul className="flex-1 space-y-1 p-2">
              {column.items.map((card) => (
                <li
                  key={card.id}
                  draggable={!move.isPending}
                  onDragStart={(event) => {
                    event.dataTransfer.setData(DRAG_TYPE,
                      JSON.stringify({ cardId: card.id, fromKey: column.key }))
                    event.dataTransfer.effectAllowed = 'move'
                    setDragging(card.id)
                  }}
                  onDragEnd={() => { setDragging(null); setOver(null) }}
                  className={`rounded border border-ink-200 bg-surface p-2 ${
                    move.isPending ? '' : 'cursor-grab active:cursor-grabbing'} ${
                    dragging === card.id ? 'opacity-50' : ''}`}
                >
                  <p className="text-xs text-ink-500">{card.stableId}</p>
                  <p className="text-sm text-ink-900">{card.title}</p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    <Badge tone={card.priority === 'critical' ? 'critical'
                      : card.priority === 'high' ? 'warning' : 'muted'}>
                      {card.priority}
                    </Badge>
                    {card.approvedVersion
                      ? <Badge tone="good">approved</Badge>
                      : <Badge tone="muted">draft</Badge>}
                    {card.blockedReason ? <Badge tone="critical">blocked</Badge> : null}
                  </div>
                  {card.blockedReason ? (
                    <p className="mt-1 text-xs text-red-800">
                      <span className="font-medium">Blocked by:</span> {card.blockedReason}
                    </p>
                  ) : null}
                  <div className="relative mt-2">
                    <button
                      type="button"
                      data-move-button={card.id}
                      className="btn-ghost w-full justify-start px-1 py-0.5 text-xs"
                      aria-expanded={menuFor === card.id}
                      aria-controls={`move-menu-${card.id}`}
                      aria-label={`Move ${card.stableId} to another column`}
                      onClick={() => setMenuFor(menuFor === card.id ? null : card.id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Escape') setMenuFor(null)
                      }}
                    >
                      <span aria-hidden>⇄</span> Move to…
                    </button>
                    {menuFor === card.id ? (
                      <ul id={`move-menu-${card.id}`}
                          className="mt-1 space-y-0.5 rounded border border-ink-200 bg-surface p-1"
                          onKeyDown={(event) => {
                            if (event.key !== 'Escape') return
                            setMenuFor(null)
                            boardRef.current?.querySelector<HTMLElement>(
                              `[data-move-button="${card.id}"]`)?.focus()
                          }}>
                        {board.columns.filter((c) => c.key !== column.key).map((target) => (
                          <li key={target.key}>
                            <button type="button"
                                    className="w-full rounded px-2 py-1 text-left text-xs
                                               text-ink-800 hover:bg-ink-100"
                                    onClick={() => requestMove(card, column.key, target.key,
                                                               { keepFocus: true })}>
                              {target.name}
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </li>
              ))}
              {!column.items.length ? (
                <li className="rounded border border-dashed border-ink-300 px-2 py-4 text-center
                               text-xs text-ink-500">
                  {dragging ? 'Drop here' : 'No items'}
                </li>
              ) : null}
            </ul>
          </section>
        ))}
      </div>
      <CreateModal
        open={pendingBlock !== null}
        title={pendingBlock ? `Block ${pendingBlock.card.stableId}` : 'Block item'}
        submitLabel={pendingBlock ? `Move to ${columnName(pendingBlock.toKey)}` : 'Move'}
        onClose={() => {
          if (pendingBlock) setAnnouncement(`${pendingBlock.card.stableId} was not moved.`)
          setPendingBlock(null)
        }}
        onSubmit={confirmBlock}
      >
        <Field label="What is it blocked by?"
               hint="Shown on the card until it leaves the column. Moving it out clears it.">
          <textarea className="input h-24" required value={reason}
                    onChange={(event) => setReason(event.target.value)} />
        </Field>
      </CreateModal>
    </>
  )
}
