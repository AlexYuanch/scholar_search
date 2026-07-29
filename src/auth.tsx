import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api"

export interface AuthUser {
  id: string
  username: string
  display_name: string
  avatar_key: "initials" | "sage" | "ocean" | "sunset" | "plum" | "gold"
  theme: "default" | "green" | "purple" | "orange"
  role: "user" | "admin" | "super_admin"
  can_view_admin: boolean
  can_manage_admins: boolean
}

interface AuthContextValue {
  loading: boolean
  user: AuthUser | null
  signIn: (username: string, password: string) => Promise<void>
  register: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  refreshUser: () => Promise<void>
  updateProfile: (preferences: Pick<AuthUser, "display_name" | "avatar_key" | "theme">) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
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
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshUser = useCallback(async () => {
    try {
      const response = await request("/auth/me")
      if (!response.ok) throw new Error(`Auth request failed (${response.status})`)
      const payload = await response.json()
      setUser(payload.authenticated ? payload.user : null)
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let active = true
    void request("/auth/me").then(async (response) => {
      if (!response.ok) throw new Error(`Auth request failed (${response.status})`)
      const payload = await response.json()
      if (active) setUser(payload.authenticated ? payload.user : null)
    }).catch(() => {
      if (active) setUser(null)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    loading,
    user,
    refreshUser,
    updateProfile: async (preferences) => {
      const response = await request("/account/profile", {
        method: "PATCH",
        body: JSON.stringify(preferences),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? `Profile update failed (${response.status})`)
      setUser(payload.user)
    },
    changePassword: async (currentPassword, newPassword) => {
      const response = await request("/account/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? `Password update failed (${response.status})`)
      setUser(payload.user)
    },
    signIn: async (username: string, password: string) => {
      const response = await request("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? `Login request failed (${response.status})`)
      setUser(payload.user)
    },
    register: async (username: string, password: string) => {
      const response = await request("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? `Registration failed (${response.status})`)
      setUser(payload.user)
    },
    signOut: async () => {
      const response = await request("/auth/logout", { method: "POST" })
      if (!response.ok) throw new Error(`Sign out failed (${response.status})`)
      setUser(null)
    },
  }), [loading, refreshUser, user])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error("useAuth must be used inside AuthProvider")
  return context
}
