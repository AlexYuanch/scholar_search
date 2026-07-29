import { useEffect, useRef, useState } from "react"
import { Check, KeyRound, LogOut, Settings, X } from "lucide-react"
import { useAuth, type AuthUser } from "@/auth"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import type { Lang } from "@/i18n"

const avatarKeys: AuthUser["avatar_key"][] = ["initials", "sage", "ocean", "sunset", "plum", "gold"]
const themeKeys: AuthUser["theme"][] = ["default", "green", "purple", "orange"]

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
    const close = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", close)
    document.addEventListener("keydown", escape)
    return () => {
      document.removeEventListener("mousedown", close)
      document.removeEventListener("keydown", escape)
    }
  }, [open])

  if (!user) return null

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
          onClick={() => setOpen((value) => !value)}
        >
          <UserAvatar user={user} />
        </button>
        {open && (
          <div className="scholar-user-popover">
            <div className="scholar-user-summary">
              <UserAvatar user={user} className="h-10 w-10" />
              <div>
                <strong>{user.display_name || user.username}</strong>
                <span>@{user.username}</span>
              </div>
            </div>
            <button type="button" onClick={() => {
              setDisplayName(user.display_name || user.username)
              setAvatarKey(user.avatar_key)
              setTheme(user.theme)
              setMessage("")
              setSettingsOpen(true)
              setOpen(false)
            }}>
              <Settings />{zh ? "个人设置" : "Account settings"}
            </button>
            <button type="button" onClick={() => void signOut()}>
              <LogOut />{zh ? "退出登录" : "Sign out"}
            </button>
          </div>
        )}
      </div>

      {settingsOpen && (
        <div className="scholar-settings-layer" role="dialog" aria-modal="true">
          <button
            type="button"
            className="scholar-settings-backdrop"
            aria-label={zh ? "关闭设置" : "Close settings"}
            onClick={() => setSettingsOpen(false)}
          />
          <section className="scholar-settings-dialog">
            <header>
              <div>
                <p>{zh ? "账户" : "Account"}</p>
                <h2>{zh ? "个人设置" : "Personal settings"}</h2>
              </div>
              <Button variant="ghost" size="icon" onClick={() => setSettingsOpen(false)}>
                <X className="h-4 w-4" />
              </Button>
            </header>

            <div className="scholar-settings-content">
              <section>
                <h3>{zh ? "公开显示" : "Profile"}</h3>
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
                  <span className="scholar-settings-label">{zh ? "主题色" : "Accent color"}</span>
                  <div className="scholar-theme-options">
                    {themeKeys.map((key) => (
                      <button
                        type="button"
                        key={key}
                        aria-pressed={theme === key}
                        className={`scholar-theme-swatch scholar-theme-swatch--${key}`}
                        onClick={() => setTheme(key)}
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

              <section>
                <h3><KeyRound />{zh ? "修改密码" : "Change password"}</h3>
                <label>
                  <span>{zh ? "当前密码" : "Current password"}</span>
                  <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} />
                </label>
                <label>
                  <span>{zh ? "新密码（至少 12 位）" : "New password (12+ characters)"}</span>
                  <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
                </label>
                <label>
                  <span>{zh ? "确认新密码" : "Confirm new password"}</span>
                  <input type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} />
                </label>
                <Button
                  variant="outline"
                  onClick={() => void savePassword()}
                  disabled={saving || currentPassword.length < 12 || newPassword.length < 12}
                >
                  {zh ? "更新密码" : "Update password"}
                </Button>
              </section>
              {message && <p className="scholar-settings-message">{message}</p>}
            </div>
          </section>
        </div>
      )}
    </>
  )
}
