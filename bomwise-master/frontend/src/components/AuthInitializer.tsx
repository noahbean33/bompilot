import { type ReactNode, useEffect, useState } from 'react'
import { refresh } from '../api/auth'
import { useAuthStore } from '../store/authStore'

/**
 * Runs once on mount to silently restore the session from the httpOnly
 * refresh-token cookie.  Renders nothing until the attempt completes so
 * ProtectedRoute never sees a briefly-null token and flashes the login page.
 */
export function AuthInitializer({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const setToken = useAuthStore((s) => s.setToken)

  useEffect(() => {
    refresh()
      .then((t) => setToken(t.access_token))
      .catch(() => {
        /* no valid cookie → user will be redirected to /login */
      })
      .finally(() => setReady(true))
  }, [setToken])

  if (!ready) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  return <>{children}</>
}
