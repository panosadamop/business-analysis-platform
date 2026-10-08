/** Session state: the signed in user and the project currently in context. */
import { create } from 'zustand'

import { api, tokenStore } from './api'
import type { PublicUser } from '../types'

interface SessionState {
  user: PublicUser | null
  status: 'unknown' | 'authenticated' | 'anonymous'
  signIn: (email: string, password: string) => Promise<PublicUser>
  signOut: () => void
  restore: () => Promise<void>
}

export const useSession = create<SessionState>((set) => ({
  user: null,
  status: 'unknown',
  async signIn(email, password) {
    const response = await api<{ accessToken: string; user: PublicUser }>('/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    tokenStore.set(response.accessToken)
    set({ user: response.user, status: 'authenticated' })
    return response.user
  },
  signOut() {
    tokenStore.set(null)
    set({ user: null, status: 'anonymous' })
  },
  async restore() {
    if (!tokenStore.get()) {
      set({ status: 'anonymous', user: null })
      return
    }
    try {
      const user = await api<PublicUser>('/auth/me')
      set({ user, status: 'authenticated' })
    } catch {
      tokenStore.set(null)
      set({ status: 'anonymous', user: null })
    }
  },
}))

export function hasRole(user: PublicUser | null, role: string) {
  return Boolean(user?.globalRoles.includes(role))
}
