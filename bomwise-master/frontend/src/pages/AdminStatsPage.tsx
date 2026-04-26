import { useQuery } from '@tanstack/react-query'
import { fetchAdminStats, fetchProviderStatus, type AdminStats } from '../api/admin'

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{value}</p>
    </div>
  )
}

function MatchRateCard({ pct, matched, total }: { pct: number; matched: number; total: number }) {
  const colour = pct > 80 ? 'bg-green-500' : pct > 50 ? 'bg-amber-400' : 'bg-red-500'
  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <p className="text-xs font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">Match rate</p>
      <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{pct}%</p>
      <div className="mt-2 h-1.5 w-full rounded-full bg-gray-200 dark:bg-gray-700">
        <div className={`h-1.5 rounded-full ${colour}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
      <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">{matched} / {total} lines matched</p>
    </div>
  )
}

function ProviderBreakdown({ stats }: { stats: AdminStats }) {
  // Fetch daily limits from provider status to colour the badges correctly
  const { data: providerStatus } = useQuery({
    queryKey: ['adminProviderStatus'],
    queryFn: fetchProviderStatus,
    staleTime: 60_000,
  })

  const limitMap: Record<string, number | null> = {}
  providerStatus?.forEach((p) => { limitMap[p.name] = p.daily_limit })

  const entries = Object.entries(stats.providers_breakdown)
  if (entries.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">No providers registered.</p>
  }

  return (
    <div className="flex flex-wrap gap-2">
      {entries.map(([name, calls]) => {
        const limit = limitMap[name] ?? null
        const pct = limit != null ? (calls / limit) * 100 : 0
        const colour =
          limit == null
            ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400'
            : pct > 90
            ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
            : pct > 70
            ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
            : 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'

        return (
          <span
            key={name}
            className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${colour}`}
          >
            <span className="font-mono">{name}</span>
            <span className="opacity-70">·</span>
            <span>{calls} call{calls !== 1 ? 's' : ''}</span>
            {limit != null && (
              <span className="opacity-60">/ {limit}</span>
            )}
          </span>
        )
      })}
    </div>
  )
}

export function AdminStatsPage() {
  const { data: stats, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['adminStats'],
    queryFn: fetchAdminStats,
  })

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Statistics</h1>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      )}

      {isError && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          Failed to load statistics.
        </div>
      )}

      {stats && (
        <div className="space-y-8">
          {/* Users */}
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
              Users
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <StatCard label="Total users" value={stats.users_total} />
              <StatCard label="Active last 30 days" value={stats.users_active_30d} />
              <StatCard label="Pro subscribers" value={stats.pro_users_total} />
              <StatCard label="Free users" value={stats.free_users_total} />
            </div>
          </section>

          {/* Projects & BOM */}
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
              Projects &amp; BOM
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <StatCard label="Total projects" value={stats.projects_total} />
              <StatCard label="Avg projects / user" value={stats.projects_per_user_avg} />
              <StatCard label="Total BOM lines" value={stats.bom_lines_total} />
              <StatCard label="Matched lines" value={stats.bom_lines_matched} />
              <MatchRateCard
                pct={stats.match_rate_pct}
                matched={stats.bom_lines_matched}
                total={stats.bom_lines_total}
              />
            </div>
          </section>

          {/* Provider usage */}
          <section>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-400 dark:text-gray-500">
              Provider usage today
            </h2>
            <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
              <ProviderBreakdown stats={stats} />
            </div>
          </section>
        </div>
      )}
    </div>
  )
}
