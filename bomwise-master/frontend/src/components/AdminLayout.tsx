import { NavLink, Outlet, Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { me } from '../api/auth'

export function AdminLayout() {
  const { data: user, isLoading } = useQuery({
    queryKey: ['currentUser'],
    queryFn: me,
  })

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-white dark:bg-gray-900">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!user?.is_admin) {
    return <Navigate to="/projects" replace />
  }

  return (
    <div className="flex min-h-0 flex-1 gap-6">
      {/* Admin sidebar */}
      <aside className="w-48 shrink-0">
        <p className="mb-3 px-2 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
          Admin
        </p>
        <nav className="space-y-1">
          {[
            { to: '/admin/providers', label: 'Provider Health' },
            { to: '/admin/stats', label: 'Statistics' },
            { to: '/admin/users', label: 'Users' },
            { to: '/admin/ai', label: 'AI Usage' },
            { to: '/admin/settings', label: 'Settings' },
          ].map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm font-medium ${
                  isActive
                    ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400'
                    : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-gray-100'
                }`
              }
            >
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Page content */}
      <div className="min-w-0 flex-1">
        <Outlet />
      </div>
    </div>
  )
}
