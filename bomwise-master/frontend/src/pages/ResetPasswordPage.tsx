import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { resetPassword } from '../api/auth'

const inputCls = 'w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100'

export function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') ?? ''
  const navigate = useNavigate()

  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (newPassword !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setLoading(true)
    try {
      await resetPassword(token, newPassword)
      navigate('/login?reset=success', { replace: true })
    } catch {
      setError('Invalid or expired reset link. Please request a new one.')
    } finally {
      setLoading(false)
    }
  }

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
        <div className="rounded-xl bg-white p-8 text-center shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <p className="text-sm text-red-600 dark:text-red-400">Invalid reset link.</p>
          <Link to="/forgot-password" className="mt-3 inline-block text-sm text-blue-600 hover:underline dark:text-blue-400">
            Request a new one
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
      <div className="w-full max-w-sm">
        <div className="mb-8">
          <div className="flex items-center justify-center gap-2">
            <img src="/mag_glass_logo_transparent.png" alt="Logo" className="h-10 w-auto dark:hidden" />
            <img src="/mag_glass_logo_transparent_dark.png" alt="Logo" className="hidden h-10 w-auto dark:block" />
            <span className="text-xl font-bold tracking-tight text-blue-600 dark:text-blue-400">BOMexplorer</span>
          </div>
          <p className="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">Set a new password</p>
        </div>

        <p className="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">
          Need help?{' '}
          <a
            href="https://connect.techexplorations.com/create-a-support-ticket"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            Tech Explorations Help Desk
          </a>
        </p>

        <form
          onSubmit={handleSubmit}
          className="mt-4 rounded-xl bg-white p-8 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700"
        >
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                New password
              </label>
              <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)}
                required autoFocus minLength={8} className={inputCls} />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Confirm new password
              </label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                required minLength={8} className={inputCls} />
            </div>
          </div>

          {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="mt-6 w-full rounded-md bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Updating…' : 'Update password'}
          </button>
        </form>
      </div>
    </div>
  )
}
