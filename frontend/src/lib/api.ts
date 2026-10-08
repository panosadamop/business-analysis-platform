/**
 * Typed API client.
 *
 * Every call carries the bearer token and surfaces the server's structured
 * error payload, so a permission denial or a version conflict can be shown to
 * the user exactly as the server described it.
 */

const BASE = '/api/v1'

export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly details: unknown

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  /** A version conflict carries a refreshed manifest the caller can re-preview. */
  get isVersionConflict() {
    return this.code === 'version_conflict'
  }

  get isPolicyBlocked() {
    return this.code === 'policy_blocked_egress'
  }
}

const TOKEN_KEY = 'ait.token'

export const tokenStore = {
  get: () => {
    try {
      return localStorage.getItem(TOKEN_KEY)
    } catch {
      return null
    }
  },
  set: (token: string | null) => {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, token)
      else localStorage.removeItem(TOKEN_KEY)
    } catch {
      /* storage can be unavailable; the session simply does not persist */
    }
  },
}

type Options = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  query?: Record<string, string | number | boolean | undefined | null>
  idempotencyKey?: string
  raw?: boolean
}

function buildUrl(path: string, query?: Options['query']) {
  const url = new URL(BASE + path, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    }
  }
  return url.pathname + url.search
}

export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = tokenStore.get()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  let body: BodyInit | undefined
  if (options.body instanceof FormData) {
    body = options.body
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  const response = await fetch(buildUrl(path, options.query), {
    method: options.method ?? 'GET',
    headers,
    body,
  })

  // A rejected sign in is reported as the server described it. Only a 401 on
  // another call means the stored session is no longer valid.
  const isSignIn = path.startsWith('/auth/login')
  if (response.status === 401 && !isSignIn) {
    tokenStore.set(null)
    if (!window.location.pathname.startsWith('/login')) {
      window.location.assign('/login')
    }
    throw new ApiError(401, 'unauthorized', 'Your session has expired', null)
  }

  if (!response.ok) {
    let payload: { error?: { code?: string; message?: string; details?: unknown } } = {}
    try {
      payload = await response.json()
    } catch {
      /* non JSON error body */
    }
    throw new ApiError(
      response.status,
      payload.error?.code ?? 'error',
      payload.error?.message ?? response.statusText,
      payload.error?.details ?? null,
    )
  }

  if (options.raw) return response as unknown as T
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export async function download(path: string, filename: string) {
  const response = await api<Response>(path, { raw: true })
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function uploadSource(
  projectId: string,
  file: File,
  meta: Record<string, unknown>,
  documentId?: string,
) {
  const form = new FormData()
  form.append('file', file)
  form.append('meta', JSON.stringify(meta))
  // Re-importing an existing document creates a new version of it.
  if (documentId) form.append('document_id', documentId)
  return api(`/projects/${projectId}/sources`, { method: 'POST', body: form })
}
