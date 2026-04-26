import { useState } from 'react'
import { Link } from 'react-router-dom'
import { forgotPassword } from '../api/auth'

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    try {
      await forgotPassword(email)
    } finally {
      setLoading(false)
      setSubmitted(true)
    }
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
          <p className="mt-2 text-center text-sm text-gray-500 dark:text-gray-400">Reset your password</p>
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

        <div className="mt-4 rounded-xl bg-white p-8 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          {submitted ? (
            <div className="text-center">
              <p className="text-sm text-gray-700 dark:text-gray-300">
                If that email is registered, you'll receive a reset link shortly.
              </p>
              <Link
                to="/login"
                className="mt-4 inline-block text-sm text-blue-600 hover:underline dark:text-blue-400"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
                  Email address
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

              <button
                type="submit"
                disabled={loading}
                className="w-full rounded-md bg-blue-600 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? 'Sending…' : 'Send reset link'}
              </button>

              <p className="text-center text-sm text-gray-500 dark:text-gray-400">
                <Link to="/login" className="text-blue-600 hover:underline dark:text-blue-400">
                  Back to sign in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
