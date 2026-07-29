import { useEffect, useRef, useState } from "react"
import { ArrowLeft, Check, KeyRound, LogOut, Settings, X } from "lucide-react"
import { useAuth, type AuthUser } from "@/auth"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import type { Lang } from "@/i18n"

const avatarKeys: AuthUser["avatar_key"][] = ["initials", "sage", "ocean", "sunset", "plum", "gold"]
const themeKeys: AuthUser["theme"][] = ["default", "green", "purple", "orange"]
const themeClasses = ["theme-green", "theme-purple", "theme-orange"]

function applyTheme(theme: AuthUser["theme"]) {
  const root = document.documentElement
  root.classList.remove(...themeClasses)
  if (theme !== "default") root.classList.add(`theme-${theme}`)
}

function initials(value: string) {
  const parts = value.trim().split(/\s+/).filter(Boolean)
  return (parts.length > 1 ? `${parts[0][0]}${parts.at(-1)?.[0]}` : value.slice(0, 2)).toUpperCase()
}

export function UserAvatar({ user, className = "" }: { user: AuthUser; className?: string }) {
  return (
    <Avatar className={`scholar-account-avatar scholar-avatar--${user.avatar_key} ${className}`}>
      <AvatarFallback>{initials(user.display_name || user.username)}</AvatarFallback>
    </Avatar>
  )
}

export default function UserMenu({ lang }: { lang: Lang }) {
  const { user, signOut, updateProfile, changePassword } = useAuth()
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsSection, setSettingsSection] = useState<"profile" | "password">("profile")
  const [displayName, setDisplayName] = useState(user?.display_name || user?.username || "")
  const [avatarKey, setAvatarKey] = useState<AuthUser["avatar_key"]>(user?.avatar_key || "initials")
  const [theme, setTheme] = useState<AuthUser["theme"]>(user?.theme || "default")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState("")
  const wrapperRef = useRef<HTMLDivElement>(null)
  const zh = lang === "zh"

  useEffect(() => {
    if (!open) return
    const closeMenu = () => {
      applyTheme(user?.theme ?? "default")
      setOpen(false)
      setSettingsOpen(false)
    }
    const close = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) closeMenu()
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu()
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", escape)
    }
  }, [open, user?.theme])

  if (!user) return null

  const closeMenu = () => {
    applyTheme(user.theme)
    setOpen(false)
    setSettingsOpen(false)
    setMessage("")
  }

  const openMenu = () => {
    setDisplayName(user.display_name || user.username)
    setAvatarKey(user.avatar_key)
    setTheme(user.theme)
    setSettingsSection("profile")
    setMessage("")
    setOpen(true)
    setSettingsOpen(false)
  }

  const openSettings = () => {
    setDisplayName(user.display_name || user.username)
    setAvatarKey(user.avatar_key)
    setTheme(user.theme)
    setSettingsSection("profile")
    setMessage("")
    setSettingsOpen(true)
  }

  const saveProfile = async () => {
    setSaving(true)
    setMessage("")
    try {
      await updateProfile({
        display_name: displayName.trim(),
        avatar_key: avatarKey,
        theme,
      })
      setMessage(zh ? "个人设置已保存" : "Profile settings saved")
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : (zh ? "保存失败" : "Save failed"))
    } finally {
      setSaving(false)
    }
  }

  const savePassword = async () => {
    if (newPassword !== confirmPassword) {
      setMessage(zh ? "两次输入的新密码不一致" : "New passwords do not match")
      return
    }
    setSaving(true)
    setMessage("")
    try {
      await changePassword(currentPassword, newPassword)
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
      setMessage(zh ? "密码已更新" : "Password updated")
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : (zh ? "密码更新失败" : "Password update failed"))
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div ref={wrapperRef} className="scholar-user-menu">
        <button
          type="button"
          className="scholar-avatar-button"
          aria-label={zh ? "打开账户菜单" : "Open account menu"}
          aria-expanded={open}
          onClick={() => {
            if (open) closeMenu()
            else openMenu()
          }}
        >
          <UserAvatar user={user} />
        </button>
        {open && (
          <div
            className={`scholar-user-popover${settingsOpen ? " scholar-user-popover--settings" : ""}`}
            role={settingsOpen ? "dialog" : "menu"}
            aria-label={settingsOpen ? (zh ? "个人设置" : "Personal settings") : (zh ? "账户菜单" : "Account menu")}
          >
            {settingsOpen ? (
              <>
                <header className="scholar-settings-header">
                  <button
                    type="button"
                    aria-label={zh ? "返回账户菜单" : "Back to account menu"}
                    onClick={() => {
                      applyTheme(user.theme)
                      setSettingsOpen(false)
                      setMessage("")
                    }}
                  >
                    <ArrowLeft />
                  </button>
                  <div>
                    <span>{zh ? "账户" : "Account"}</span>
                    <strong>{zh ? "个人设置" : "Personal settings"}</strong>
                  </div>
                  <button type="button" aria-label={zh ? "关闭设置" : "Close settings"} onClick={closeMenu}>
                    <X />
                  </button>
                </header>

                <div className="scholar-settings-tabs" role="tablist">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={settingsSection === "profile"}
                    onClick={() => setSettingsSection("profile")}
                  >
                    {zh ? "外观与昵称" : "Profile"}
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={settingsSection === "password"}
                    onClick={() => setSettingsSection("password")}
                  >
                    {zh ? "账户安全" : "Security"}
                  </button>
                </div>

                <div className="scholar-settings-content">
                  {settingsSection === "profile" ? (
                    <section>
                      <label>
                        <span>{zh ? "昵称" : "Display name"}</span>
                        <input value={displayName} maxLength={40} onChange={(event) => setDisplayName(event.target.value)} />
                      </label>
                      <div>
                        <span className="scholar-settings-label">{zh ? "头像" : "Avatar"}</span>
                        <div className="scholar-avatar-options">
                          {avatarKeys.map((key) => (
                            <button
                              type="button"
                              key={key}
                              aria-label={`${zh ? "头像" : "Avatar"} ${key}`}
                              aria-pressed={avatarKey === key}
                              className={`scholar-avatar-option scholar-avatar--${key}`}
                              onClick={() => setAvatarKey(key)}
                            >
                              {initials(displayName || user.username)}
                              {avatarKey === key && <Check />}
                            </button>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="scholar-settings-label">{zh ? "主题色（选择后立即预览）" : "Accent color (live preview)"}</span>
                        <div className="scholar-theme-options">
                          {themeKeys.map((key) => (
                            <button
                              type="button"
                              key={key}
                              aria-label={`${zh ? "主题色" : "Accent color"} ${key}`}
                              aria-pressed={theme === key}
                              className={`scholar-theme-swatch scholar-theme-swatch--${key}`}
                              onClick={() => {
                                setTheme(key)
                                applyTheme(key)
                              }}
                            >
                              {theme === key && <Check />}
                            </button>
                          ))}
                        </div>
                      </div>
                      <Button onClick={() => void saveProfile()} disabled={saving || !displayName.trim()}>
                        {saving ? (zh ? "保存中" : "Saving") : (zh ? "保存个人设置" : "Save profile")}
                      </Button>
                    </section>
                  ) : (
                    <section>
                      <div className="scholar-settings-section-title">
                        <KeyRound />
                        <div>
                          <strong>{zh ? "修改密码" : "Change password"}</strong>
                          <span>{zh ? "更新后其他设备需要重新登录" : "Other devices will need to sign in again"}</span>
                        </div>
                      </div>
                      <label>
                        <span>{zh ? "当前密码" : "Current password"}</span>
                        <input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
                      </label>
                      <label>
                        <span>{zh ? "新密码（至少 12 位）" : "New password (12+ characters)"}</span>
                        <input type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
                      </label>
                      <label>
                        <span>{zh ? "确认新密码" : "Confirm new password"}</span>
                        <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
                      </label>
                      <Button
                        variant="outline"
                        onClick={() => void savePassword()}
                        disabled={saving || currentPassword.length < 12 || newPassword.length < 12}
                      >
                        {zh ? "更新密码" : "Update password"}
                      </Button>
                    </section>
                  )}
                  {message && <p className="scholar-settings-message" role="status">{message}</p>}
                </div>
              </>
            ) : (
              <>
                <div className="scholar-user-summary">
                  <UserAvatar user={user} className="h-10 w-10" />
                  <div>
                    <strong>{user.display_name || user.username}</strong>
                    <span>@{user.username}</span>
                  </div>
                </div>
                <button type="button" role="menuitem" onClick={openSettings}>
                  <Settings />{zh ? "个人设置" : "Account settings"}
                </button>
                <button type="button" role="menuitem" onClick={() => void signOut()}>
                  <LogOut />{zh ? "退出登录" : "Sign out"}
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </>
  )
}
