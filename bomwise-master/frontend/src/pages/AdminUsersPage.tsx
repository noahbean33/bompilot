import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchUsers, type AdminUserSummary } from '../api/admin'
import { useDebounce } from '../hooks/useDebounce'

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function Badge({ label, variant }: { label: string; variant: 'green' | 'red' | 'amber' | 'blue' | 'gray' }) {
  const colours: Record<string, string> = {
    green: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    blue: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    gray: 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400',
  }
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${colours[variant]}`}>
      {label}
    </span>
  )
}

function UserRow({ user }: { user: AdminUserSummary }) {
  const navigate = useNavigate()
  return (
    <tr
      className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50"
      onClick={() => navigate(`/admin/users/${user.id}`)}
    >
      <td className="px-4 py-3 text-sm text-gray-900 dark:text-gray-100">{user.email}</td>
      <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{user.name ?? '—'}</td>
      <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums dark:text-gray-300">{user.projects_count}</td>
      <td className="px-4 py-3 text-sm text-right tabular-nums">
        {user.ai_assist_lines_this_month > 0 ? (
          <span className="font-medium text-amber-700 dark:text-amber-400">{user.ai_assist_lines_this_month}</span>
        ) : (
          <span className="text-gray-400 dark:text-gray-500">0</span>
        )}
      </td>
      <td className="px-4 py-3">
        {user.is_admin && <Badge label="admin" variant="amber" />}
      </td>
      <td className="px-4 py-3">
        {user.trial_status === 'active-trial' && (
          <Badge label="active-trial" variant="blue" />
        )}
        <Badge
          label={user.is_active ? 'active' : 'disabled'}
          variant={user.is_active ? 'green' : 'red'}
        />
      </td>
      <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">{formatDate(user.created_at)}</td>
    </tr>
  )
}

export function AdminUsersPage() {
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 20

  const debouncedSearch = useDebounce(search, 300)

  const handleSearch = useCallback((value: string) => {
    setSearch(value)
    setPage(1)
  }, [])

  const { data, isLoading, isError } = useQuery({
    queryKey: ['adminUsers', page, debouncedSearch],
    queryFn: () => fetchUsers({ page, page_size: PAGE_SIZE, search: debouncedSearch || undefined }),
  })

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Users</h1>
        {data && (
          <span className="text-sm text-gray-500 dark:text-gray-400">{data.total} total</span>
        )}
      </div>

      {/* Search */}
      <div className="mb-4">
        <input
          type="text"
          placeholder="Search by email…"
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
          className="w-full max-w-sm rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:placeholder-gray-500"
        />
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      )}

      {isError && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          Failed to load users.
        </div>
      )}

      {data && (
        <>
          <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
              <thead className="bg-gray-50 dark:bg-gray-900/50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Email</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Name</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Projects</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400" title="AI Assist lines processed this calendar month">AI Lines / mo</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Role</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Status / Trial</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Joined</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400 dark:text-gray-500">
                      No users found.
                    </td>
                  </tr>
                ) : (
                  data.items.map((user) => <UserRow key={user.id} user={user} />)
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm text-gray-600 dark:text-gray-400">
              <span>
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:hover:bg-gray-700"
                >
                  Previous
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded border border-gray-300 px-3 py-1 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:hover:bg-gray-700"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
