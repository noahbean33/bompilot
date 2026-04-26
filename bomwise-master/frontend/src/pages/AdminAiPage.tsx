import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAiUsage, type AiUsageResponse } from '../api/admin'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  LineChart, Line,
} from 'recharts'

// Date helpers
function formatDate(d: Date): string {
  return d.toISOString().split('T')[0]
}

function prettyDate(d: string): string {
  return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

// Period presets
const PRESETS = [
  { label: 'Today', days: 0 },
  { label: 'Week', days: 7 },
  { label: 'Month', days: 30 },
  { label: 'Year', days: 365 },
] as const

type Preset = (typeof PRESETS)[number]['label'] | 'Custom'

function getDateRange(preset: Preset, customStart?: string, customEnd?: string) {
  if (preset === 'Custom' && customStart && customEnd) {
    return { start_date: customStart, end_date: customEnd }
  }
  const def = PRESETS.find(p => p.label === preset)
  const end = new Date()
  const start = new Date()
  start.setDate(start.getDate() - (def?.days ?? 0))
  return { start_date: formatDate(start), end_date: formatDate(end) }
}

interface ChartDataPoint {
  date: string
  [feature: string]: string | number
}

// Chart data builders
function buildBarData(data: AiUsageResponse): ChartDataPoint[] {
  const map: Record<string, ChartDataPoint> = {}
  for (const d of data.daily) {
    if (!map[d.date]) map[d.date] = { date: d.date }
    map[d.date][d.feature] = (map[d.date][d.feature] as number ?? 0) + d.total_cost_usd
  }
  return Object.values(map).sort((a, b) => a.date.localeCompare(b.date))
}

function buildLineData(data: AiUsageResponse): ChartDataPoint[] {
  const map: Record<string, ChartDataPoint> = {}
  for (const d of data.daily) {
    if (!map[d.date]) map[d.date] = { date: d.date }
    map[d.date][d.feature] = (map[d.date][d.feature] as number ?? 0) + d.total_tokens
  }
  return Object.values(map).sort((a, b) => a.date.localeCompare(b.date))
}

// Feature color map
const FEATURE_COLORS: Record<string, string> = {
  'NL Query (AI-5)': '#3b82f6',
  'AI Assist (part matching)': '#10b981',
  'AI Advisor (parts explainer)': '#f59e0b',
}

export function AdminAiPage() {
  const [preset, setPreset] = useState<Preset>('Today')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [chartType, setChartType] = useState<'cost' | 'tokens'>('cost')

  const dateRange = getDateRange(preset, customStart, customEnd)
  const query = useQuery({
    queryKey: ['adminAiUsage', dateRange],
    queryFn: () => fetchAiUsage(dateRange),
  })

  const { data, isLoading, isError, refetch, isFetching } = query

  const barData = data ? buildBarData(data) : []
  const lineData = data ? buildLineData(data) : []

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">AI Usage</h1>
          {data && (
            <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">
              {prettyDate(data.start_date)} — {prettyDate(data.end_date)}
            </p>
          )}
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        >
          {isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Period presets */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            onClick={() => setPreset(p.label)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              preset === p.label
                ? 'bg-blue-600 text-white'
                : 'border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700'
            }`}
          >
            {p.label}
          </button>
        ))}
        <button
          onClick={() => setPreset('Custom')}
          className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
            preset === 'Custom'
              ? 'bg-blue-600 text-white'
              : 'border border-gray-300 text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700'
          }`}
        >
          Custom
        </button>

        {preset === 'Custom' && (
          <div className="ml-2 flex items-center gap-2">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="rounded-lg border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            />
            <span className="text-xs text-gray-400">→</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="rounded-lg border border-gray-300 px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
            />
          </div>
        )}

        {/* Chart type toggle */}
        <div className="ml-auto flex gap-1 rounded-lg border border-gray-300 p-0.5 dark:border-gray-600">
          <button
            onClick={() => setChartType('cost')}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              chartType === 'cost' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' : 'text-gray-500'
            }`}
          >
            Cost
          </button>
          <button
            onClick={() => setChartType('tokens')}
            className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
              chartType === 'tokens' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300' : 'text-gray-500'
            }`}
          >
            Tokens
          </button>
        </div>
      </div>

      {isLoading && (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      )}

      {isError && (
        <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
          Failed to load AI usage data.
        </div>
      )}

      {data && data.daily.length === 0 && (
        <div className="rounded-lg bg-gray-50 p-8 text-center dark:bg-gray-900/50">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            No AI usage data available for the selected period.
          </p>
          <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
            The migration may not have been applied yet, or there have been no AI calls in this date range.
          </p>
        </div>
      )}

      {data && data.daily.length > 0 && (
        <div className="space-y-6">
          {/* Chart */}
          <div className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <h3 className="mb-4 text-sm font-semibold text-gray-900 dark:text-gray-100">
              {chartType === 'cost' ? 'Estimated Cost (USD)' : 'Token Usage'}
            </h3>
            <ResponsiveContainer width="100%" height={300}>
              {chartType === 'cost' ? (
                <BarChart data={barData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-gray-200 dark:stroke-gray-700" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} className="dark:stroke-gray-500" />
                  <YAxis tick={{ fontSize: 11 }} className="dark:stroke-gray-500" />
                  <Tooltip formatter={(value) => {
                    const n = typeof value === 'number' ? value : Number(value)
                    return isNaN(n) ? String(value) : `$${n.toFixed(4)}`
                  }} />
                  <Legend />
                  {Object.keys(FEATURE_COLORS).map((feat) => (
                    <Bar
                      key={feat}
                      dataKey={feat}
                      stackId="a"
                      fill={FEATURE_COLORS[feat]}
                    />
                  ))}
                </BarChart>
              ) : (
                <LineChart data={lineData}>
                  <CartesianGrid strokeDasharray="3 3" className="stroke-gray-200 dark:stroke-gray-700" />
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} className="dark:stroke-gray-500" />
                  <YAxis tick={{ fontSize: 11 }} className="dark:stroke-gray-500" />
                  <Tooltip formatter={(value) => {
                    const n = typeof value === 'number' ? value : Number(value)
                    return isNaN(n) ? String(value) : n.toLocaleString()
                  }} />
                  <Legend />
                  {Object.keys(FEATURE_COLORS).map((feat) => (
                    <Line
                      key={feat}
                      type="monotone"
                      dataKey={feat}
                      stroke={FEATURE_COLORS[feat]}
                      dot={false}
                    />
                  ))}
                </LineChart>
              )}
            </ResponsiveContainer>
          </div>

          {/* Summary cards */}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {data.summary.map((entry) => (
              <div
                key={entry.feature}
                className="rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700"
              >
                <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">{entry.feature}</h3>
                <dl className="mt-3 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-xs text-gray-400 dark:text-gray-500">Total tokens</dt>
                    <dd className="font-medium text-gray-700 dark:text-gray-300">{entry.total_tokens.toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-xs text-gray-400 dark:text-gray-500">Input tokens</dt>
                    <dd className="text-gray-700 dark:text-gray-300">{entry.input_tokens.toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-xs text-gray-400 dark:text-gray-500">Output tokens</dt>
                    <dd className="text-gray-700 dark:text-gray-300">{entry.output_tokens.toLocaleString()}</dd>
                  </div>
                  <div className="flex justify-between border-t border-gray-100 pt-2 dark:border-gray-700">
                    <dt className="text-xs font-medium text-gray-600 dark:text-gray-400">Est. cost</dt>
                    <dd className="font-semibold text-gray-900 dark:text-gray-100">
                      ${entry.total_cost_usd.toFixed(4)}
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </div>

          {/* Total cost */}
          <div className="rounded-xl bg-gray-50 p-4 ring-1 ring-gray-200 dark:bg-gray-900/50 dark:ring-gray-700">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Total estimated cost</span>
              <span className="text-lg font-semibold text-gray-900 dark:text-gray-100">
                ${data.total_cost_usd.toFixed(4)}
              </span>
            </div>
          </div>

          {/* Rate note */}
          <p className="text-xs text-gray-400 dark:text-gray-500">{data.rate_note}</p>
        </div>
      )}
    </div>
  )
}