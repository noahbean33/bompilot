import { useState } from 'react'
import { Link } from 'react-router-dom'
import { register } from '../api/auth'

export function SignupPage() {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [success, setSuccess] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  async function doRegister() {
    setLoading(true)
    try {
      await register(email, name)
      setSuccess(true)
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Registration failed. Please try again.')
    } finally {
      setLoading(false)
      setShowConfirm(false)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (!email) return
    setShowConfirm(true)
  }

  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50 px-4 dark:bg-gray-900">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <div className="flex items-center justify-center gap-2">
              <img src="/mag_glass_logo_transparent.png" alt="Logo" className="h-10 w-auto dark:hidden" />
              <img src="/mag_glass_logo_transparent_dark.png" alt="Logo" className="hidden h-10 w-auto dark:block" />
              <span className="text-xl font-bold tracking-tight text-blue-600 dark:text-blue-400">BOMexplorer</span>
            </div>
            <p className="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">Account created!</p>
          </div>

          <div className="rounded-xl bg-white p-8 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <div className="mb-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700 ring-1 ring-green-200 dark:bg-green-950 dark:text-green-300 dark:ring-green-800">
              Account created successfully. Check your email for a link to set your password.
            </div>
            <Link
              to="/login"
              className="block w-full rounded-md bg-blue-600 py-2 text-center text-sm font-medium text-white hover:bg-blue-700"
            >
              Sign in
            </Link>
          </div>
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
          <p className="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">Create your account</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl bg-white p-8 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700"
        >
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoFocus
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-500"
                placeholder="you@example.com"
              />
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                Full name (optional)
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-500"
                placeholder="Your name"
              />
            </div>
          </div>

          <p className="mt-4 text-xs text-gray-500 dark:text-gray-400">
            After clicking <strong>Sign up</strong>, an email will be sent with a unique link so you can set your password and log in. Please double-check your email address is correct.
          </p>

          {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="mt-6 w-full rounded-md bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? 'Creating account…' : 'Sign up'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-gray-500 dark:text-gray-400">
          Already have an account?{' '}
          <Link to="/login" className="text-blue-600 hover:underline dark:text-blue-400">
            Sign in
          </Link>
        </p>
      </div>

      {/* Email confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-lg dark:bg-gray-800">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Is your email correct?</h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
              We'll send a password-set link to: <strong>{email}</strong>
            </p>
            <div className="mt-6 flex gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                No, go back
              </button>
              <button
                onClick={doRegister}
                disabled={loading}
                className="flex-1 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? 'Sending…' : 'Yes, proceed'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
