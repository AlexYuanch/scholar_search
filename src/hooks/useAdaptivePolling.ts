import { useEffect } from "react"

const POLL_DELAYS_MS = [3_000, 5_000, 10_000, 20_000]

export function useAdaptivePolling(
  active: boolean,
  poll: () => Promise<unknown>,
) {
  useEffect(() => {
    if (!active) return
    let cancelled = false
    let delayIndex = 0
    let timer: number | undefined

    const schedule = () => {
      if (cancelled) return
      const delay = POLL_DELAYS_MS[
        Math.min(delayIndex, POLL_DELAYS_MS.length - 1)
      ]
      timer = window.setTimeout(async () => {
        if (cancelled) return
        if (document.visibilityState === "visible") {
          await poll().catch(() => undefined)
          delayIndex += 1
        }
        schedule()
      }, delay)
    }

    const handleVisibility = () => {
      if (document.visibilityState !== "visible" || cancelled) return
      if (timer !== undefined) window.clearTimeout(timer)
      delayIndex = 0
      void poll().catch(() => undefined).finally(schedule)
    }

    document.addEventListener("visibilitychange", handleVisibility)
    schedule()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
      document.removeEventListener("visibilitychange", handleVisibility)
    }
  }, [active, poll])
}
