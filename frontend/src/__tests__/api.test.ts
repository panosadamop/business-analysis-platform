/** The API client: error mapping, authentication and request shaping. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, tokenStore } from '../lib/api'

function respondWith(body: unknown, init: ResponseInit = {}) {
  return vi.fn().mockResolvedValue(
    new Response(typeof body === 'string' ? body : JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
      ...init,
    }),
  )
}

describe('api client', () => {
  beforeEach(() => {
    tokenStore.set(null)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the bearer token when one is stored', async () => {
    const fetchMock = respondWith({ ok: true })
    vi.stubGlobal('fetch', fetchMock)
    tokenStore.set('token-123')

    await api('/projects')

    const [, init] = fetchMock.mock.calls[0]
    expect((init.headers as Record<string, string>).Authorization)
      .toBe('Bearer token-123')
  })

  it('omits the Authorization header when signed out', async () => {
    const fetchMock = respondWith([])
    vi.stubGlobal('fetch', fetchMock)

    await api('/projects')

    const [, init] = fetchMock.mock.calls[0]
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined()
  })

  it('builds the query string, dropping empty values', async () => {
    const fetchMock = respondWith([])
    vi.stubGlobal('fetch', fetchMock)

    await api('/projects/p1/search', {
      query: { q: 'invoice', limit: 10, empty: '', missing: undefined, nothing: null },
    })

    const [url] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/projects/p1/search?q=invoice&limit=10')
  })

  it('passes the idempotency key through as a header', async () => {
    const fetchMock = respondWith({ id: 'job-1' })
    vi.stubGlobal('fetch', fetchMock)

    await api('/projects/p1/exports', { method: 'POST', body: {},
                                        idempotencyKey: 'key-1' })

    const [, init] = fetchMock.mock.calls[0]
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBe('key-1')
    expect(init.method).toBe('POST')
  })

  it('does not set a JSON content type for multipart uploads', async () => {
    const fetchMock = respondWith({ id: 'source-1' })
    vi.stubGlobal('fetch', fetchMock)

    const form = new FormData()
    form.append('meta', '{}')
    await api('/projects/p1/sources', { method: 'POST', body: form })

    const [, init] = fetchMock.mock.calls[0]
    expect((init.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('maps a structured server error onto ApiError', async () => {
    vi.stubGlobal('fetch', respondWith(
      { error: { code: 'forbidden', message: 'Not allowed',
                 details: { missing: ['cost.read'] } } },
      { status: 403 },
    ))

    await expect(api('/projects/p1/cost-summary')).rejects.toMatchObject({
      status: 403,
      code: 'forbidden',
      message: 'Not allowed',
      details: { missing: ['cost.read'] },
    })
  })

  it('recognises a version conflict so the approval screen can re-preview', async () => {
    vi.stubGlobal('fetch', respondWith(
      { error: { code: 'version_conflict', message: 'An item changed',
                 details: { refreshedManifestId: 'm2' } } },
      { status: 409 },
    ))

    const error = await api('/projects/p1/approvals/decisions', { method: 'POST' })
      .catch((caught) => caught as ApiError)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isVersionConflict).toBe(true)
    expect((error as ApiError).details).toEqual({ refreshedManifestId: 'm2' })
  })

  it('recognises a policy blocked egress response', async () => {
    vi.stubGlobal('fetch', respondWith(
      { error: { code: 'policy_blocked_egress', message: 'Blocked by policy' } },
      { status: 451 },
    ))

    const error = await api('/projects/p1/analysis/runs', { method: 'POST' })
      .catch((caught) => caught as ApiError)
    expect((error as ApiError).isPolicyBlocked).toBe(true)
  })

  it('clears the token and redirects on 401', async () => {
    vi.stubGlobal('fetch', respondWith({}, { status: 401 }))
    const assign = vi.fn()
    vi.stubGlobal('location', { origin: 'http://localhost',
                                pathname: '/projects/p1', assign })
    tokenStore.set('expired')

    await expect(api('/projects')).rejects.toBeInstanceOf(ApiError)
    expect(tokenStore.get()).toBeNull()
    expect(assign).toHaveBeenCalledWith('/login')
  })

  it('falls back to the status text when the body is not JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response('<html>502</html>', { status: 502, statusText: 'Bad Gateway' })))

    await expect(api('/projects')).rejects.toMatchObject({
      status: 502, code: 'error', message: 'Bad Gateway',
    })
  })

  it('returns undefined for an empty 204 response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })))
    await expect(api('/projects/p1/thing')).resolves.toBeUndefined()
  })

  it('survives unavailable storage without throwing', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('blocked')
      },
    })
    expect(() => tokenStore.get()).not.toThrow()
    expect(() => tokenStore.set('x')).not.toThrow()
    if (original) Object.defineProperty(window, 'localStorage', original)
  })
})
