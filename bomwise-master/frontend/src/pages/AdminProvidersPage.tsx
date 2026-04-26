import { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchProviderStatus,
  pingProvider,
  fetchProviderErrors,
  clearProviderErrors,
  type ProviderStatus,
  type PingResult,
  type ProviderErrorEntry,
} from '../api/admin'

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function errorRowColour(errorType: string): string {
  if (errorType === 'auth_failure' || errorType === 'rate_limit')
    return 'text-red-600 dark:text-red-400'
  if (errorType === 'timeout' || errorType === 'http_error')
    return 'text-amber-600 dark:text-amber-400'
  return 'text-gray-500 dark:text-gray-400'
}

function UsageBar({ calls, limit }: { calls: number; limit: number }) {
  const pct = Math.min(100, Math.round((calls / limit) * 100))
  const colour =
    pct > 90 ? 'bg-red-500' : pct > 70 ? 'bg-amber-400' : 'bg-green-500'
  return (
    <div className="mt-1 h-1.5 w-full rounded-full bg-gray-200 dark:bg-gray-700">
      <div className={`h-1.5 rounded-full ${colour}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

function ErrorLogEntry({ entry }: { entry: ProviderErrorEntry }) {
  const truncated =
    entry.message.length > 80 ? entry.message.slice(0, 80) + '…' : entry.message
  return (
    <p className={`font-mono text-xs leading-5 ${errorRowColour(entry.error_type)}`}>
      [{formatTime(entry.occurred_at)}]{' '}
      <span className="font-semibold">{entry.error_type}</span>
      {' — '}
      {truncated}
    </p>
  )
}

function ErrorLogSection({ providerName }: { providerName: string }) {
  const queryClient = useQueryClient()
  const [expanded, setExpanded] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)

  const limit = expanded ? 500 : 10
  const errorsKey = ['providerErrors', providerName, limit]

  const { data, isLoading } = useQuery({
    queryKey: errorsKey,
    queryFn: () => fetchProviderErrors(providerName, limit),
    staleTime: 30_000,
  })

  const clearMutation = useMutation({
    mutationFn: () => clearProviderErrors(providerName),
    onSuccess: () => {
      setConfirmClear(false)
      // Invalidate both limit variants
      queryClient.invalidateQueries({ queryKey: ['providerErrors', providerName] })
    },
  })

  const total = data?.total_in_24h ?? 0
  const errors = data?.errors ?? []

  return (
    <div className="mt-4 border-t border-gray-100 pt-4 dark:border-gray-700">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
          Error Log (24 h)
        </p>
        {total > 0 && (
          <div className="flex items-center gap-2">
            {confirmClear ? (
              <span className="flex items-center gap-1 text-xs">
                <span className="text-gray-500 dark:text-gray-400">Sure?</span>
                <button
                  onClick={() => clearMutation.mutate()}
                  disabled={clearMutation.isPending}
                  className="font-medium text-red-600 hover:underline dark:text-red-400"
                >
                  Yes, clear
                </button>
                <button
                  onClick={() => setConfirmClear(false)}
                  className="text-gray-400 hover:underline"
                >
                  Cancel
                </button>
              </span>
            ) : (
              <button
                onClick={() => setConfirmClear(true)}
                title="Clear error log for this provider"
                className="rounded p-0.5 text-gray-400 hover:text-red-500 dark:hover:text-red-400"
              >
                {/* trash icon */}
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </button>
            )}
          </div>
        )}
      </div>

      {isLoading && (
        <p className="text-xs text-gray-400 dark:text-gray-500">Loading…</p>
      )}

      {!isLoading && total === 0 && (
        <p className="text-xs text-gray-400 dark:text-gray-500">No errors in last 24 h</p>
      )}

      {!isLoading && total > 0 && (
        <>
          <div
            className={
              expanded
                ? 'max-h-72 overflow-y-auto'
                : ''
            }
          >
            {errors.map((e) => (
              <ErrorLogEntry key={e.id} entry={e} />
            ))}
          </div>

          {total > 10 && !expanded && (
            <button
              onClick={() => setExpanded(true)}
              className="mt-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
            >
              Expand ({total} total)
            </button>
          )}
          {expanded && (
            <button
              onClick={() => setExpanded(false)}
              className="mt-1 text-xs text-blue-600 hover:underline dark:text-blue-400"
            >
              Collapse
            </button>
          )}
        </>
      )}
    </div>
  )
}

function ProviderCard({ provider }: { provider: ProviderStatus }) {
  const [pingResult, setPingResult] = useState<PingResult | null>(null)

  const pingMutation = useMutation({
    mutationFn: () => pingProvider(provider.name),
    onSuccess: (result) => setPingResult(result),
  })

  const limitLabel =
    provider.daily_limit != null
      ? `${provider.calls_today} / ${provider.daily_limit}`
      : `${provider.calls_today} / —`

  return (
    <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <span className="font-mono text-sm font-semibold text-gray-900 dark:text-gray-100">
            {provider.name}
          </span>
          <span
            className={`ml-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
              provider.enabled
                ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                : 'bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
            }`}
          >
            {provider.enabled ? 'enabled' : 'disabled'}
          </span>
        </div>
        {provider.errors_today > 0 && (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
            {provider.errors_today} error{provider.errors_today !== 1 ? 's' : ''} today
          </span>
        )}
      </div>

      {/* Metrics */}
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-xs text-gray-400 dark:text-gray-500">Calls today / limit</p>
          <p className="font-medium text-gray-700 dark:text-gray-300">{limitLabel}</p>
          {provider.daily_limit != null && (
            <UsageBar calls={provider.calls_today} limit={provider.daily_limit} />
          )}
        </div>
        <div>
          <p className="text-xs text-gray-400 dark:text-gray-500">Last success</p>
          <p className="font-medium text-gray-700 dark:text-gray-300">
            {formatRelative(provider.last_success_at)}
          </p>
        </div>
      </div>

      {/* Ping button + result */}
      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => pingMutation.mutate()}
          disabled={pingMutation.isPending}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          {pingMutation.isPending ? 'Pinging…' : 'Ping'}
        </button>

        {pingResult && (
          <span
            className={`text-xs font-medium ${
              pingResult.success ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
            }`}
          >
            {pingResult.success
              ? `✓ ${pingResult.latency_ms} ms`
              : `✗ ${pingResult.error ?? 'error'}`}
          </span>
        )}
      </div>

      {/* Error log */}
      <ErrorLogSection providerName={provider.name} />
    </div>
  )
}

export function AdminProvidersPage() {
  const [secondsSinceRefresh, setSecondsSinceRefresh] = useState(0)

  const { data: providers, isLoading, isError, refetch } = useQuery({
    queryKey: ['adminProviderStatus'],
    queryFn: fetchProviderStatus,
    refetchInterval: 60_000,
  })

  // Tick the "last updated" counter every second; reset on refetch
  useEffect(() => {
    setSecondsSinceRefresh(0)
    const interval = setInterval(() => setSecondsSinceRefresh((s) => s + 1), 1000)
    return () => clearInterval(interval)
  }, [providers])

  const handleRefresh = useCallback(() => {
    refetch()
    setSecondsSinceRefresh(0)
  }, [refetch])

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Provider Health</h1>
          <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
            Last updated: {secondsSinceRefresh}s ago
            {' · '}
            <button
              onClick={handleRefresh}
              className="text-blue-600 hover:underline dark:text-blue-400"
            >
              Refresh now
            </button>
          </p>
        </div>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      )}

      {isError && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          Failed to load provider status.
        </div>
      )}

      {providers && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {providers.map((p) => (
            <ProviderCard key={p.name} provider={p} />
          ))}
        </div>
      )}
    </div>
  )
}
