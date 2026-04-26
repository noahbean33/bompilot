import { useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchUserPreferences, updateUserPreferences } from '../api/preferences'
import { changePassword } from '../api/auth'
import { fetchUserUsage } from '../api/users'
import { BillingPage } from './BillingPage'
import type { NlPresetFilter, NlPreset } from '../types'

const CURRENCIES = [
  'USD', 'EUR', 'GBP', 'AUD', 'CAD', 'JPY', 'CNY', 'SGD',
  'INR', 'BRL', 'MXN', 'CHF', 'HKD', 'NZD', 'SEK', 'NOK', 'DKK',
]

const DISTRIBUTORS = [
  'DigiKey', 'Mouser', 'Arrow', 'Avnet', 'Newark', 'RS Components',
  'Farnell', 'TTI', 'TME', 'LCSC', 'Allied Electronics', 'Future Electronics',
  'NextPCB',
]

const inputCls = 'mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100'

type Tab = 'preferences' | 'password' | 'billing' | 'nl-presets' | 'usage'

const FILTER_OPS = [
  { value: 'eq', label: 'equals' },
  { value: 'neq', label: 'not equals' },
  { value: 'lt', label: 'less than' },
  { value: 'lte', label: '≤' },
  { value: 'gt', label: 'greater than' },
  { value: 'gte', label: '≥' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'not contains' },
  { value: 'is_null', label: 'is null' },
  { value: 'is_not_null', label: 'is not null' },
]

const FILTER_FIELDS = [
  { value: 'reference', label: 'Reference' },
  { value: 'value', label: 'Value' },
  { value: 'footprint', label: 'Footprint' },
  { value: 'mpn_raw', label: 'MPN (Raw)' },
  { value: 'matched_mpn', label: 'Matched MPN' },
  { value: 'manufacturer', label: 'Manufacturer' },
  { value: 'category', label: 'Category' },
  { value: 'stock', label: 'Stock' },
  { value: 'unit_price', label: 'Unit Price' },
  { value: 'match_type', label: 'Match Type' },
  { value: 'locked', label: 'Locked' },
]

function emptyFilter(): NlPresetFilter {
  return { field: 'reference', op: 'eq', value: '' }
}

function emptyPreset(): NlPreset {
  return { label: 'My Preset', filters: [emptyFilter()], highlightOnly: false }
}

interface PresetEditorProps {
  draft: NlPreset
  setDraft: (draft: NlPreset) => void
  onSave: () => void
  onCancel: () => void
}

function PresetEditor({ draft, setDraft, onSave, onCancel }: PresetEditorProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={draft.label}
          onChange={(e) => setDraft({ ...draft, label: e.target.value })}
          placeholder="Preset name"
          className="flex-1 rounded border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
        />
        <label className="flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
          <input
            type="checkbox"
            checked={draft.highlightOnly}
            onChange={(e) => setDraft({ ...draft, highlightOnly: e.target.checked })}
            className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          Highlight only
        </label>
      </div>

      {/* Filters */}
      <div className="space-y-1">
        {draft.filters.map((f, fi) => (
          <div key={fi} className="flex items-center gap-2">
            <select
              value={f.field}
              onChange={(e) => {
                const next = [...draft.filters]
                next[fi] = { ...next[fi], field: e.target.value }
                setDraft({ ...draft, filters: next })
              }}
              className="w-32 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 focus:border-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            >
              {FILTER_FIELDS.map((ff) => (
                <option key={ff.value} value={ff.value}>{ff.label}</option>
              ))}
            </select>
            <select
              value={f.op}
              onChange={(e) => {
                const next = [...draft.filters]
                next[fi] = { ...next[fi], op: e.target.value }
                setDraft({ ...draft, filters: next })
              }}
              className="w-28 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 focus:border-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            >
              {FILTER_OPS.map((fo) => (
                <option key={fo.value} value={fo.value}>{fo.label}</option>
              ))}
            </select>
            {(f.op !== 'is_null' && f.op !== 'is_not_null') && (
              <input
                type="text"
                value={String(f.value ?? '')}
                onChange={(e) => {
                  const next = [...draft.filters]
                  next[fi] = { ...next[fi], value: e.target.value }
                  setDraft({ ...draft, filters: next })
                }}
                placeholder="value"
                className="flex-1 rounded border border-gray-300 bg-white px-2 py-1 text-xs text-gray-900 focus:border-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              />
            )}
            <button
              onClick={() => {
                const next = draft.filters.filter((_, j) => j !== fi)
                setDraft({ ...draft, filters: next.length ? next : [emptyFilter()] })
              }}
              className="text-xs text-red-500 hover:text-red-700 px-1"
            >✕</button>
          </div>
        ))}
        <button
          onClick={() => setDraft({ ...draft, filters: [...draft.filters, emptyFilter()] })}
          className="text-xs text-blue-500 hover:text-blue-700"
        >
          + Add condition
        </button>
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={onSave}
          className="rounded bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700"
        >
          Save
        </button>
        <button
          onClick={onCancel}
          className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

function PresetsTab() {
  const queryClient = useQueryClient()

  const { data: prefs, isPending } = useQuery({
    queryKey: ['userPreferences'],
    queryFn: fetchUserPreferences,
  })

  const [presets, setPresets] = useState<NlPreset[]>([])
  const [editingIdx, setEditingIdx] = useState<number | null>(null)
  const [editDraft, setEditDraft] = useState<NlPreset | null>(null)

  useEffect(() => {
    if (prefs?.preferred_nl_presets?.length) {
      setPresets(prefs.preferred_nl_presets as NlPreset[])
    } else {
      setPresets([])
    }
  }, [prefs?.preferred_nl_presets])

  const mutation = useMutation({
    mutationFn: (newPresets: NlPreset[]) => updateUserPreferences({ preferred_nl_presets: newPresets }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['userPreferences'], updated)
    },
  })

  function handleAdd() {
    const newPreset = emptyPreset()
    setEditingIdx(presets.length)
    setEditDraft(newPreset)
  }

  function handleSave() {
    if (editDraft == null) return
    if (!editDraft.label.trim()) return
    if (editDraft.filters.length === 0) return
    setEditingIdx(null)
    setEditDraft(null)
    if (typeof editingIdx === 'number' && editingIdx < presets.length) {
      const next = [...presets]
      next[editingIdx] = editDraft
      setPresets(next)
      mutation.mutate(next)
    } else {
      const next = [...presets, editDraft]
      setPresets(next)
      mutation.mutate(next)
    }
  }

  function handleDelete(idx: number) {
    const next = presets.filter((_, i) => i !== idx)
    setPresets(next)
    mutation.mutate(next)
  }

  function handleMoveUp(idx: number) {
    if (idx === 0) return
    const next = [...presets]
    ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
    setPresets(next)
    mutation.mutate(next)
  }

  function handleMoveDown(idx: number) {
    if (idx >= presets.length - 1) return
    const next = [...presets]
    ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
    setPresets(next)
    mutation.mutate(next)
  }

  const cardCls = 'rounded-lg border border-gray-200 p-3 bg-gray-50 dark:border-gray-600 dark:bg-gray-700'

  if (isPending) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Custom presets apply to all projects. Presets with the same label as a built-in preset will replace it.
        </p>
        <button
          onClick={handleAdd}
          className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          + Add Preset
        </button>
      </div>

      {/* Preset list */}
      <div className="space-y-3">
        {presets.length === 0 && editingIdx === null && (
          <p className="text-center py-8 text-sm text-gray-400 dark:text-gray-500">
            No custom presets yet. Click "+ Add Preset" to create one.
          </p>
        )}
        {presets.map((preset, idx) => (
          <div key={idx} className={cardCls}>
            {/* Viewing mode — only when not editing this or a new item */}
            {editingIdx !== idx && (
              <div>
                <div className="flex items-center justify-between">
                  <span className="font-medium text-sm text-gray-900 dark:text-gray-100">
                    ⚡ {preset.label}
                    {preset.highlightOnly && (
                      <span className="ml-2 text-xs text-purple-500 font-normal">(highlight only)</span>
                    )}
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleMoveUp(idx)}
                      disabled={idx === 0}
                      className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-30 px-1"
                      title="Move up"
                    >↑</button>
                    <button
                      onClick={() => handleMoveDown(idx)}
                      disabled={idx >= presets.length - 1}
                      className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-30 px-1"
                      title="Move down"
                    >↓</button>
                    <button
                      onClick={() => { setEditingIdx(idx); setEditDraft({ ...preset, filters: [...preset.filters] }) }}
                      className="text-xs text-blue-500 hover:text-blue-700 px-1"
                    >edit</button>
                    <button
                      onClick={() => handleDelete(idx)}
                      className="text-xs text-red-500 hover:text-red-700 px-1"
                    >✕</button>
                  </div>
                </div>
                <div className="mt-1 flex flex-wrap gap-1 text-xs text-gray-500 dark:text-gray-400">
                  {preset.filters.map((f, fi) => (
                    <span key={fi} className="bg-white px-1.5 py-0.5 rounded text-xs dark:bg-gray-600">
                      {f.field} {f.op}{f.value != null ? ` ${String(f.value)}` : ''}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}

        {/* New preset editor (when editingIdx >= presets.length) */}
        {editingIdx !== null && editingIdx >= presets.length && editDraft && (
          <div className={cardCls}>
            <PresetEditor draft={editDraft} setDraft={setEditDraft} onSave={handleSave} onCancel={() => { setEditingIdx(null); setEditDraft(null) }} />
          </div>
        )}

        {/* Inline editor for existing presets */}
        {editingIdx !== null && editingIdx < presets.length && editDraft && (
          <div className={cardCls}>
            <PresetEditor draft={editDraft} setDraft={setEditDraft} onSave={handleSave} onCancel={() => { setEditingIdx(null); setEditDraft(null) }} />
          </div>
        )}
      </div>

      {presets.length > 0 && (
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => mutation.mutate(presets)}
            disabled={mutation.isPending || presets.length === 0}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {mutation.isPending ? 'Saving…' : 'Save presets'}
          </button>
          {mutation.isError && <span className="text-sm text-red-600">Failed to save</span>}
        </div>
      )}
    </div>
  )
}

function PreferencesTab() {
  const queryClient = useQueryClient()

  const { data: prefs, isPending } = useQuery({
    queryKey: ['userPreferences'],
    queryFn: fetchUserPreferences,
  })

  const [currency, setCurrency] = useState('USD')
  const [selectedDist, setSelectedDist] = useState<string[]>([])
  const [autoLock, setAutoLock] = useState(true)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (prefs) {
      setCurrency(prefs.preferred_currency || 'USD')
      setSelectedDist(prefs.preferred_distributors ?? [])
      setAutoLock(prefs.auto_lock_parts ?? true)
    }
  }, [prefs])

  function toggleDist(name: string) {
    setSelectedDist((prev) =>
      prev.includes(name) ? prev.filter((d) => d !== name) : [...prev, name]
    )
  }

  const mutation = useMutation({
    mutationFn: () =>
      updateUserPreferences({
        preferred_currency: currency,
        preferred_distributors: selectedDist,
        auto_lock_parts: autoLock,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['userPreferences'], updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  if (isPending) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <p className="mb-5 text-sm text-gray-500 dark:text-gray-400">
        These are your global defaults. Individual projects can override them.
      </p>

      <div className="space-y-5">
        {/* Currency */}
        <div>
          <label htmlFor="currency" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Preferred currency
          </label>
          <select
            id="currency"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className={inputCls}
          >
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>

        {/* Distributors */}
        <div>
          <p className="block text-sm font-medium text-gray-700 dark:text-gray-300">Preferred distributors</p>
          <p className="mt-0.5 mb-2 text-xs text-gray-400 dark:text-gray-500">
            Select all that apply. Leave all unchecked to accept any distributor.
          </p>
          <div className="grid grid-cols-2 gap-1.5">
            {DISTRIBUTORS.map((d) => (
              <label key={d} className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={selectedDist.includes(d)}
                  onChange={() => toggleDist(d)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600"
                />
                {d}
              </label>
            ))}
          </div>
        </div>

        {/* Auto-lock parts */}
        <div>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={autoLock}
              onChange={(e) => setAutoLock(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600"
            />
            <div>
              <p className="text-sm font-medium text-gray-700 dark:text-gray-300">Auto-lock parts when selected</p>
              <p className="text-xs text-gray-400 dark:text-gray-500">
                Automatically lock a BOM line when you select or swap to a part. Locked lines cannot be changed until unlocked.
              </p>
            </div>
          </label>
        </div>
      </div>

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {mutation.isPending ? 'Saving…' : 'Save preferences'}
        </button>
        {saved && <span className="text-sm text-green-600 dark:text-green-400">Saved</span>}
        {mutation.isError && <span className="text-sm text-red-600 dark:text-red-400">Failed to save</span>}
      </div>
    </div>
  )
}

const PERIODS = [
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
  { id: 'year', label: 'Year' },
] as const

type Period = (typeof PERIODS)[number]['id']

function UsageTab() {
  const [period, setPeriod] = useState<Period>('week')

  const { data, isLoading } = useQuery({
    queryKey: ['userUsage', period],
    queryFn: () => fetchUserUsage(period),
  })

  const statCardCls = 'rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700'

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!data) return null

  const matchRate = data.bom_lines_total > 0
    ? `${((data.matched_lines / data.bom_lines_total) * 100).toFixed(1)}%`
    : 'N/A'

  // Format hours and minutes
  const hours = Math.floor(data.time_saved_minutes / 60)
  const mins = data.time_saved_minutes % 60
  const timeSavedStr = hours > 0 ? `~${hours}h ${mins}min` : `~${mins}min`

  return (
    <div className="space-y-5">
      {/* Period selector */}
      <div className="flex gap-1 rounded-lg bg-gray-100 p-1 dark:bg-gray-800">
        {PERIODS.map((p) => (
          <button
            key={p.id}
            onClick={() => setPeriod(p.id)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
              period === p.id
                ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Date range note */}
      <p className="text-xs text-gray-400 dark:text-gray-500">
        {data.start_date} → {data.end_date} ({data.period})
      </p>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">Projects</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.projects_count}</p>
        </div>
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">Total BOM lines</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.bom_lines_total}</p>
        </div>
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">Matched lines</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.matched_lines}</p>
          <p className="text-xs text-gray-400 dark:text-gray-500">Rate: {matchRate}</p>
        </div>
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">AI Assist (DB)</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.ai_assist_lines_db}</p>
        </div>
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">AI Assist (month)</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.ai_assist_lines_monthly}</p>
        </div>
        <div className={statCardCls}>
          <p className="text-xs text-gray-400 dark:text-gray-500">AI Advisor (month)</p>
          <p className="mt-1 text-2xl font-semibold text-gray-900 dark:text-gray-100">{data.ai_advisor_queries_monthly}</p>
        </div>
      </div>

      {/* Time saved card */}
      <div className="rounded-xl bg-gradient-to-r from-blue-50 to-emerald-50 p-5 ring-1 ring-blue-200 dark:from-blue-900/20 dark:to-emerald-900/20 dark:ring-blue-800">
        <p className="text-xs text-blue-500 dark:text-blue-400">Estimated time saved</p>
        <p className="mt-1 text-3xl font-bold text-blue-700 dark:text-blue-300">{timeSavedStr}</p>
        <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{data.time_saved_note}</p>
      </div>
    </div>
  )
}

function ChangePasswordTab() {
  const [current, setCurrent] = useState('')
  const [newPass, setNewPass] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSuccess(false)
    if (newPass !== confirm) {
      setError('New passwords do not match.')
      return
    }
    if (newPass.length < 8) {
      setError('New password must be at least 8 characters.')
      return
    }
    setLoading(true)
    try {
      await changePassword(current, newPass)
      setSuccess(true)
      setCurrent('')
      setNewPass('')
      setConfirm('')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setError(msg ?? 'Failed to change password.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <h2 className="mb-4 text-sm font-semibold text-gray-700 dark:text-gray-300">Change password</h2>
      <form onSubmit={handleSubmit} className="max-w-sm space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Current password
          </label>
          <input
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            New password
          </label>
          <input
            type="password"
            value={newPass}
            onChange={(e) => setNewPass(e.target.value)}
            required
            minLength={8}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">
            Confirm new password
          </label>
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            minLength={8}
            className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
          />
        </div>

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {success && <p className="text-sm text-green-600 dark:text-green-400">Password changed successfully.</p>}

        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {loading ? 'Updating…' : 'Update password'}
        </button>
      </form>
    </div>
  )
}

export function PreferencesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  const activeTab: Tab =
    rawTab === 'password' ? 'password' : rawTab === 'billing' ? 'billing' : rawTab === 'nl-presets' ? 'nl-presets' : rawTab === 'usage' ? 'usage' : 'preferences'

  function setTab(tab: Tab) {
    if (tab === 'preferences') {
      setSearchParams({})
    } else {
      setSearchParams({ tab })
    }
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'preferences', label: 'Preferences' },
    { id: 'usage', label: 'Usage' },
    { id: 'nl-presets', label: 'NL Presets' },
    { id: 'password', label: 'Change Password' },
    { id: 'billing', label: 'Billing' },
  ]

  return (
    <div className="mx-auto max-w-lg">
      <h1 className="mb-6 text-2xl font-semibold text-gray-900 dark:text-gray-100">Account</h1>

      {/* Tab bar */}
      <div className="mb-6 flex gap-1 rounded-lg bg-gray-100 p-1 dark:bg-gray-800">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setTab(tab.id)}
            className={`flex-1 rounded-md py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm dark:bg-gray-700 dark:text-gray-100'
                : 'text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'preferences' && <PreferencesTab />}
      {activeTab === 'usage' && <UsageTab />}
      {activeTab === 'nl-presets' && <PresetsTab />}
      {activeTab === 'password' && <ChangePasswordTab />}
      {activeTab === 'billing' && <BillingPage />}
    </div>
  )
}