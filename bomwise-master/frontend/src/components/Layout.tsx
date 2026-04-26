import { Link, Outlet, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { logout, me } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import { useTheme } from '../context/ThemeContext'
import { Footer } from './Footer'

function SunIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 3v1m0 16v1m8.66-9h-1M4.34 12h-1m15.07-6.07-.71.71M6.34 17.66l-.71.71m12.02 0-.71-.71M6.34 6.34l-.71-.71M12 7a5 5 0 1 0 0 10A5 5 0 0 0 12 7z" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  )
}

export function Layout() {
  const signOut = useAuthStore((s) => s.logout)
  const navigate = useNavigate()
  const { theme, toggle } = useTheme()

  const { data: user } = useQuery({
    queryKey: ['currentUser'],
    queryFn: me,
  })

  async function handleLogout() {
    try {
      await logout()
    } finally {
      signOut()
      navigate('/login', { replace: true })
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-gray-50 dark:bg-gray-900">
      <header className="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <Link
              to="/projects"
              className="flex items-center gap-2"
            >
              <img
                src={theme === 'dark' ? '/mag_glass_logo_transparent.png' : '/mag_glass_logo_transparent_dark.png'}
                alt="BOMexplorer"
                className="h-8 w-auto"
              />
              <span className="text-lg font-semibold tracking-tight text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300">
                BOMexplorer
              </span>
            </Link>
            <nav className="flex items-center gap-4">
              <Link
                to="/projects"
                className="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
              >
                Projects
              </Link>
              <Link
                to="/preferences"
                className="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
              >
                Account
              </Link>
              {user?.is_admin && (
                <Link
                  to="/admin"
                  className="text-sm font-medium text-amber-600 hover:text-amber-700 dark:text-amber-400 dark:hover:text-amber-300"
                >
                  Admin
                </Link>
              )}
            </nav>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggle}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              className="rounded p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
            </button>
            <button
              onClick={handleLogout}
              className="rounded px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="mx-auto max-w-7xl px-6 py-8">
          <Outlet />
        </div>
      </main>

      <Footer />
    </div>
  )
}
