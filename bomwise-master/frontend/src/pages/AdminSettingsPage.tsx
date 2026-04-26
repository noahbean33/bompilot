import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchPlatformSettings,
  updatePlatformSettings,
  fetchProviderStatus,
  type PlatformSettings,
} from '../api/admin'

// Known providers in the order they appear in the registry
const KNOWN_PROVIDERS = ['nexar', 'oemsecrets', 'mouser', 'digikey', 'findchips', 'digikey_mouser', 'nextpcb']

const inputCls = 'w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100'

function ProviderTag({
  name,
  active,
  onClick,
}: {
  name: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium transition ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-gray-100 text-gray-500 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-gray-600'
      }`}
    >
      {name}
    </button>
  )
}

export function AdminSettingsPage() {
  const queryClient = useQueryClient()

  const { data: current, isLoading, isError } = useQuery({
    queryKey: ['platformSettings'],
    queryFn: fetchPlatformSettings,
  })

  // Fetch live provider list so we can show all registered names
  const { data: providerStatus } = useQuery({
    queryKey: ['providerStatus'],
    queryFn: fetchProviderStatus,
    staleTime: 30_000,
  })

  const [maxProjects, setMaxProjects] = useState('')
  const [maxParts, setMaxParts] = useState('')
  const [fallbackOrder, setFallbackOrder] = useState('')
  const [aiAssistFree, setAiAssistFree] = useState('')
  const [aiAssistPaid, setAiAssistPaid] = useState('')
  const [saved, setSaved] = useState(false)

  // Seed form from fetched data
  useEffect(() => {
    if (current) {
      setMaxProjects(String(current.free_plan_max_projects))
      setMaxParts(String(current.free_plan_max_parts_per_project))
      setFallbackOrder(current.provider_fallback_order)
      setAiAssistFree(String(current.ai_assist_free_monthly_lines))
      setAiAssistPaid(String(current.ai_assist_paid_monthly_lines))
    }
  }, [current])

  const mutation = useMutation({
    mutationFn: (body: PlatformSettings) => updatePlatformSettings(body),
    onSuccess: (updated) => {
      queryClient.setQueryData(['platformSettings'], updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const proj = parseInt(maxProjects, 10)
    const parts = parseInt(maxParts, 10)
    const aiFree = parseInt(aiAssistFree, 10)
    const aiPaid = parseInt(aiAssistPaid, 10)
    if (isNaN(proj) || proj < 1 || isNaN(parts) || parts < 1) return
    if (isNaN(aiFree) || aiFree < 0 || isNaN(aiPaid) || aiPaid < 0) return
    mutation.mutate({
      free_plan_max_projects: proj,
      free_plan_max_parts_per_project: parts,
      provider_fallback_order: fallbackOrder.trim(),
      ai_assist_free_monthly_lines: aiFree,
      ai_assist_paid_monthly_lines: aiPaid,
    })
  }

  // Build the list of all provider names: registered ones + any in the current order string
  const registeredNames = providerStatus?.map((p) => p.name) ?? KNOWN_PROVIDERS
  const orderList = fallbackOrder
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
  const allProviders = Array.from(new Set([...registeredNames, ...orderList]))

  function toggleProvider(name: string) {
    if (orderList.includes(name)) {
      setFallbackOrder(orderList.filter((n) => n !== name).join(','))
    } else {
      setFallbackOrder([...orderList, name].join(','))
    }
  }

  function moveProvider(name: string, direction: -1 | 1) {
    const idx = orderList.indexOf(name)
    if (idx < 0) return
    const next = [...orderList]
    const swap = idx + direction
    if (swap < 0 || swap >= next.length) return
    ;[next[idx], next[swap]] = [next[swap], next[idx]]
    setFallbackOrder(next.join(','))
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        Failed to load platform settings.
      </div>
    )
  }

  return (
    <div>
      <h1 className="mb-6 text-xl font-semibold text-gray-900 dark:text-gray-100">Platform Settings</h1>

      <form onSubmit={handleSubmit} className="space-y-6">

        {/* Free plan limits */}
        <section className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <h2 className="mb-1 text-sm font-semibold text-gray-700 dark:text-gray-300">Free plan defaults</h2>
          <p className="mb-4 text-xs text-gray-400 dark:text-gray-500">
            Applied to all free-plan users who do not have a per-user override set.
            Paid users are always unlimited.
          </p>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="max-projects"
                className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400"
              >
                Max projects per user
              </label>
              <input
                id="max-projects"
                type="number"
                min={1}
                required
                value={maxProjects}
                onChange={(e) => setMaxProjects(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label
                htmlFor="max-parts"
                className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400"
              >
                Max parts per project
              </label>
              <input
                id="max-parts"
                type="number"
                min={1}
                required
                value={maxParts}
                onChange={(e) => setMaxParts(e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
        </section>

        {/* Provider fallback order */}
        <section className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <h2 className="mb-1 text-sm font-semibold text-gray-700 dark:text-gray-300">Default data sources</h2>
          <p className="mb-4 text-xs text-gray-400 dark:text-gray-500">
            Providers are tried left-to-right when matching parts. Toggle to include/exclude;
            use ↑ ↓ to reorder. Changes take effect on the next match run — they do not
            affect providers configured per-project.
          </p>

          {/* Active order */}
          {orderList.length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Active order</p>
              <div className="flex flex-wrap gap-2">
                {orderList.map((name, idx) => (
                  <div key={name} className="flex items-center gap-1">
                    <span className="rounded-full bg-blue-600 px-3 py-1 text-xs font-medium text-white">
                      {idx + 1}. {name}
                    </span>
                    <button
                      type="button"
                      onClick={() => moveProvider(name, -1)}
                      disabled={idx === 0}
                      className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs leading-none dark:text-gray-500 dark:hover:text-gray-300"
                      title="Move up"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      onClick={() => moveProvider(name, 1)}
                      disabled={idx === orderList.length - 1}
                      className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs leading-none dark:text-gray-500 dark:hover:text-gray-300"
                      title="Move down"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleProvider(name)}
                      className="text-gray-400 hover:text-red-500 text-xs leading-none dark:text-gray-500"
                      title="Remove"
                    >
                      ×
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Available providers to toggle */}
          <div>
            <p className="mb-1.5 text-xs font-medium text-gray-500 dark:text-gray-400">Available providers</p>
            <div className="flex flex-wrap gap-2">
              {allProviders.map((name) => (
                <ProviderTag
                  key={name}
                  name={name}
                  active={orderList.includes(name)}
                  onClick={() => toggleProvider(name)}
                />
              ))}
            </div>
          </div>

          {/* Raw text fallback */}
          <div className="mt-4">
            <label className="block text-xs font-medium text-gray-500 mb-1 dark:text-gray-400">
              Raw fallback order string
            </label>
            <input
              type="text"
              value={fallbackOrder}
              onChange={(e) => setFallbackOrder(e.target.value)}
              placeholder="e.g. nexar,oemsecrets,mouser"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 font-mono text-xs text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
            />
            <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">
              Comma-separated. Empty string = use the provider_fallback_order from .env.
            </p>
          </div>
        </section>

        {/* AI Assist monthly line budget */}
        <section className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <h2 className="mb-1 text-sm font-semibold text-gray-700 dark:text-gray-300">AI Assist monthly line budget</h2>
          <p className="mb-4 text-xs text-gray-400 dark:text-gray-500">
            Maximum BOM lines processed by AI Assist per user per month.
            Set to <span className="font-mono">0</span> for unlimited.
            Per-user overrides on the User detail page take precedence.
          </p>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label
                htmlFor="ai-assist-free"
                className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400"
              >
                Free plan (lines/month)
              </label>
              <input
                id="ai-assist-free"
                type="number"
                min={0}
                required
                value={aiAssistFree}
                onChange={(e) => setAiAssistFree(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label
                htmlFor="ai-assist-paid"
                className="block text-xs font-medium text-gray-600 mb-1 dark:text-gray-400"
              >
                Paid plan (lines/month)
              </label>
              <input
                id="ai-assist-paid"
                type="number"
                min={0}
                required
                value={aiAssistPaid}
                onChange={(e) => setAiAssistPaid(e.target.value)}
                className={inputCls}
              />
            </div>
          </div>
        </section>

        {/* Save */}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {mutation.isPending ? 'Saving…' : 'Save settings'}
          </button>
          {saved && <span className="text-sm text-green-600 dark:text-green-400">Settings saved</span>}
          {mutation.isError && (
            <span className="text-sm text-red-600 dark:text-red-400">Save failed</span>
          )}
        </div>
      </form>
    </div>
  )
}
