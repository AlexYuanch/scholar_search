import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api"

export interface AuthUser {
  id: string
  email: string
}

interface MagicLinkResult {
  devMagicLink?: string
}

interface AuthContextValue {
  configured: boolean
  loading: boolean
  user: AuthUser | null
  signInWithEmail: (email: string) => Promise<MagicLinkResult>
  signOut: () => Promise<void>
  refreshUser: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function request(path: string, init: RequestInit = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  })
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const configured = import.meta.env.VITE_AUTH_ENABLED !== "false"
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(configured)

  const refreshUser = useCallback(async () => {
    if (!configured) {
      setLoading(false)
      return
    }
    try {
      const response = await request("/auth/me")
      if (!response.ok) throw new Error(`Auth request failed (${response.status})`)
      const payload = await response.json()
      setUser(payload.authenticated ? payload.user : null)
    } finally {
      setLoading(false)
    }
  }, [configured])

  useEffect(() => {
    let active = true
    if (configured) {
      void request("/auth/me").then(async (response) => {
        if (!response.ok) throw new Error(`Auth request failed (${response.status})`)
        const payload = await response.json()
        if (active) setUser(payload.authenticated ? payload.user : null)
      }).catch(() => {
        if (active) setUser(null)
      }).finally(() => {
        if (active) setLoading(false)
      })
    }
    const current = new URL(window.location.href)
    if (current.searchParams.has("login")) {
      current.searchParams.delete("login")
      window.history.replaceState({}, "", `${current.pathname}${current.search}${current.hash}`)
    }
    return () => { active = false }
  }, [configured])

  const value = useMemo<AuthContextValue>(() => ({
    configured,
    loading,
    user,
    refreshUser,
    signInWithEmail: async (email: string) => {
      if (!configured) throw new Error("Email login is disabled")
      const response = await request("/auth/magic-link", {
        method: "POST",
        body: JSON.stringify({ email }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? `Login request failed (${response.status})`)
      return { devMagicLink: payload.dev_magic_link }
    },
    signOut: async () => {
      const response = await request("/auth/logout", { method: "POST" })
      if (!response.ok) throw new Error(`Sign out failed (${response.status})`)
      setUser(null)
    },
  }), [configured, loading, refreshUser, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used inside AuthProvider")
  return context
}
