import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchBomLines,
  fetchPartResults,
  fetchSubstitutionHistory,
  fetchAlternatives,
  selectPartResult,
  swapPart,
  lockBomLine,
  unlockBomLine,
  runAiAdvisor,
} from '../api/bom'
import { fetchUserPreferences } from '../api/preferences'
import type { AiAdvisorResult, PartAlternative, PartResult, SubstitutionHistoryEntry } from '../types'

function formatDate(iso: string): string {
  const d = new Date(iso)
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`
}

export function VariantsPage() {
  const { id, lineId } = useParams<{ id: string; lineId: string }>()
  const projectId = Number(id)
  const bomLineId = Number(lineId)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [showHistory, setShowHistory] = useState(false)
  const [swapConfirm, setSwapConfirm] = useState<PartAlternative | null>(null)
  const [providerWarning, setProviderWarning] = useState(false)
  const [lockToast, setLockToast] = useState<string | null>(null)
  const [selectedAltIds, setSelectedAltIds] = useState<Set<number>>(new Set())
  const [advisorResults, setAdvisorResults] = useState<(AiAdvisorResult & { timestamp: string })[]>([])
  const [advisorLoading, setAdvisorLoading] = useState(false)

  const { data: lines } = useQuery({
    queryKey: ['bom', projectId],
    queryFn: () => fetchBomLines(projectId),
    enabled: !isNaN(projectId),
  })

  const line = lines?.find((l) => l.id === bomLineId)

  const {
    data: results,
    isPending: resultsPending,
    isError: resultsError,
  } = useQuery({
    queryKey: ['partResults', projectId, bomLineId],
    queryFn: () => fetchPartResults(projectId, bomLineId),
    enabled: !isNaN(projectId) && !isNaN(bomLineId),
  })

  const { data: alternatives } = useQuery({
    queryKey: ['alternatives', projectId, bomLineId],
    queryFn: () => fetchAlternatives(projectId, bomLineId),
    enabled: !isNaN(projectId) && !isNaN(bomLineId),
  })

  const advisorMutation = useMutation({
    mutationFn: (mpns: string[]) => runAiAdvisor(projectId, bomLineId, mpns),
    onSuccess: (data, mpns) => {
      setAdvisorResults((prev) => [...prev, { ...data, mpns, timestamp: new Date().toISOString() }])
      setAdvisorLoading(false)
    },
    onError: () => {
      setAdvisorLoading(false)
    },
  })

  function toggleAlt(id: number) {
    setSelectedAltIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else {
        if (next.size >= 3) return prev
        next.add(id)
      }
      return next
    })
  }

  function handleExplainSelected() {
    if (!alternatives || selectedAltIds.size === 0 || selectedAltIds.size > 3) return
    const selected = alternatives.filter((a) => selectedAltIds.has(a.id))
    const mpns = selected.map((a) => a.mpn)
    setAdvisorLoading(true)
    advisorMutation.mutate(mpns)
  }

  const { data: history } = useQuery({
    queryKey: ['substitutionHistory', projectId, bomLineId],
    queryFn: () => fetchSubstitutionHistory(projectId, bomLineId),
    enabled: !isNaN(projectId) && !isNaN(bomLineId),
  })

  const isLocked = line?.locked ?? false

  // Auto-lock helper: checks user pref then locks (must be before mutations that use it)
  async function autoLockIfNeeded() {
    try {
      const prefs = await fetchUserPreferences()
      if (prefs.auto_lock_parts) {
        await lockBomLine(projectId, bomLineId)
        queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      }
    } catch {
      // Silently fail — lock is a best-effort enhancement
    }
  }

  const lockMutation = useMutation({
    mutationFn: (locked: boolean) =>
      locked ? lockBomLine(projectId, bomLineId) : unlockBomLine(projectId, bomLineId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  const selectMutation = useMutation({
    mutationFn: (resultId: number) =>
      selectPartResult(projectId, bomLineId, resultId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      queryClient.invalidateQueries({ queryKey: ['substitutionHistory', projectId, bomLineId] })
      autoLockIfNeeded()
    },
  })

  const swapMutation = useMutation({
    mutationFn: (alt: PartAlternative) =>
      swapPart(projectId, bomLineId, alt.mpn, alt.manufacturer),
    onSuccess: async (data) => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      queryClient.invalidateQueries({ queryKey: ['partResults', projectId, bomLineId] })
      queryClient.invalidateQueries({ queryKey: ['alternatives', projectId, bomLineId] })
      queryClient.invalidateQueries({ queryKey: ['substitutionHistory', projectId, bomLineId] })
      setSwapConfirm(null)
      if (data.provider_error) {
        setProviderWarning(true)
      } else {
        await autoLockIfNeeded()
        navigate(`/projects/${projectId}`)
      }
    },
  })

  const selectedId = line?.selected_result?.id
  const currentMpn = line?.selected_result?.mpn ?? line?.mpn_raw ?? '—'

  return (
    <div>
      {/* Back button */}
      <Link
        to={`/projects/${projectId}`}
        className="mb-4 inline-flex items-center gap-1 text-sm text-blue-600 hover:underline dark:text-blue-400"
      >
        ← Back to project
      </Link>

      {/* Provider warning banner */}
      {providerWarning && (
        <div className="mb-4 flex items-start justify-between rounded-xl border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800 dark:border-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-300">
          <span>
            Swap complete, but provider lookup failed. Pricing data may be stale.
          </span>
          <button
            onClick={() => setProviderWarning(false)}
            className="ml-4 font-medium hover:text-yellow-900 dark:hover:text-yellow-200"
          >
            ✕
          </button>
        </div>
      )}

      {/* Page title */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Part Detail & Alternatives</h1>
            {isLocked && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                🔒 Locked
              </span>
            )}
            {isLocked && (
              <span className="text-xs text-gray-400 dark:text-gray-500">
                Unlock to make changes
              </span>
            )}
          </div>
          {line && (
            <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-3">
              {line.reference && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">Reference</dt>
                  <dd className="font-mono text-gray-700 dark:text-gray-300">{line.reference}</dd>
                </div>
              )}
              {line.value && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">Value</dt>
                  <dd className="font-mono text-gray-700 dark:text-gray-300">{line.value}</dd>
                </div>
              )}
              {line.footprint && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">Footprint</dt>
                  <dd className="font-mono text-gray-700 dark:text-gray-300">{line.footprint}</dd>
                </div>
              )}
              {line.mpn_raw && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">MPN</dt>
                  <dd className="font-mono text-gray-700 dark:text-gray-300">{line.mpn_raw}</dd>
                </div>
              )}
              {line.description && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">Description</dt>
                  <dd className="text-gray-700 dark:text-gray-300 line-clamp-2">{line.description}</dd>
                </div>
              )}
              {line.notes && (
                <div>
                  <dt className="text-xs font-medium text-gray-400 dark:text-gray-500">Comments</dt>
                  <dd className="text-gray-700 dark:text-gray-300 line-clamp-2">{line.notes}</dd>
                </div>
              )}
            </dl>
          )}
        </div>
        {line && (
          <button
            onClick={() => lockMutation.mutate(!isLocked)}
            disabled={lockMutation.isPending}
            title={isLocked ? 'Unlock this part' : 'Lock this part'}
            className="shrink-0 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            {isLocked ? '🔒 Unlock' : '🔓 Lock'}
          </button>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 1 — Current part (distributor offers)                       */}
      {/* ------------------------------------------------------------------ */}
       <div className="mb-3 flex items-center justify-between">
         <div>
           <h2 className="text-base font-semibold text-gray-800 dark:text-gray-200">Current and alternative parts</h2>
           <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
             Different distributor offers for the same or similar parts. Select the best option based on price, stock, and distributor preference.
           </p>
         </div>
         {isLocked ? (
           <button
             disabled
             onClick={(e) => { e.preventDefault(); setLockToast('manual search') }}
             title="🔒 Unlock to make changes"
             className="cursor-not-allowed rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-300 dark:bg-gray-700 dark:text-gray-600"
           >
             🔍 Manual search
           </button>
         ) : (
           <Link
             to={`/projects/${projectId}/bom/${lineId}/search`}
             className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
           >
             🔍 Manual search
           </Link>
         )}
       </div>
      {resultsPending ? (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      ) : resultsError || !results ? (
        <p className="text-red-600 dark:text-red-400">Failed to load part results.</p>
      ) : results.length === 0 ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 py-16 text-center dark:border-gray-700">
          <p className="text-gray-500 dark:text-gray-400">No part results yet.</p>
          <p className="mt-1 text-sm text-gray-400 dark:text-gray-500">
            Run matching from the project page first.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <table className="min-w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400">
                <th className="px-4 py-3">#</th>
                <th className="px-4 py-3">MPN</th>
                <th className="px-4 py-3">Manufacturer</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Distributor</th>
                <th className="px-4 py-3 text-right">Stock</th>
                <th className="px-4 py-3 text-right">Unit Price</th>
                <th className="px-4 py-3">Datasheet</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
               {results
                 .sort((a, b) => {
                   const aSelected = a.id === selectedId ? 0 : 1
                   const bSelected = b.id === selectedId ? 0 : 1
                   if (aSelected !== bSelected) return aSelected - bSelected
                   return a.rank - b.rank
                 })
                 .map((result) => (
                   <ResultRow
                     key={result.id}
                     result={result}
                     isSelected={result.id === selectedId}
                     isSelecting={
                       selectMutation.isPending &&
                       selectMutation.variables === result.id
                     }
                     isLocked={isLocked}
                     onLockedClick={() => setLockToast('select')}
                     onSelect={() => selectMutation.mutate(result.id)}
                   />
                 ))}
            </tbody>
          </table>
          <div className="border-t border-gray-200 px-4 py-2 text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500">
            {results.length} {results.length === 1 ? 'candidate' : 'candidates'}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Section 2 — Alternative parts                                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="mt-10">
        <div className="mb-4">
          <h2 className="text-base font-semibold text-gray-800 dark:text-gray-200">Alternative parts</h2>
          <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
            Different parts that can substitute for the current selection. Swap to an alternative to replace the part entirely.
          </p>
        </div>

        {/* Swap confirmation overlay */}
        {swapConfirm && (
          <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-sm dark:border-blue-800 dark:bg-blue-900/20">
            <p className="font-medium text-blue-900 dark:text-blue-300">
              Swap from{' '}
              <span className="font-mono">{currentMpn}</span> to{' '}
              <span className="font-mono">{swapConfirm.mpn}</span>?
            </p>
            <p className="mt-0.5 text-blue-700 dark:text-blue-400">
              This will re-query the provider for pricing and stock data.
            </p>
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => swapMutation.mutate(swapConfirm)}
                disabled={swapMutation.isPending}
                className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {swapMutation.isPending ? 'Swapping…' : 'Confirm'}
              </button>
              <button
                onClick={() => setSwapConfirm(null)}
                disabled={swapMutation.isPending}
                className="rounded-lg bg-white px-4 py-1.5 text-xs font-medium text-gray-700 ring-1 ring-gray-300 hover:bg-gray-50 disabled:opacity-60 dark:bg-gray-700 dark:text-gray-300 dark:ring-gray-600 dark:hover:bg-gray-600"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {!alternatives || alternatives.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 py-10 text-center dark:border-gray-700">
            <p className="text-sm text-gray-500 dark:text-gray-400">No alternative parts found.</p>
            <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
              Re-import the BOM to search for alternatives.
            </p>
          </div>
        ) : (
          <>
            {/* Selection controls */}
            <div className="mb-3 flex items-center justify-between">
              <button
                onClick={() => setSelectedAltIds(new Set())}
                className="text-xs text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              >
                {selectedAltIds.size > 0 ? `Clear selection (${selectedAltIds.size})` : 'Select parts to compare'}
              </button>
               <div className="flex items-center gap-2">
                 {selectedAltIds.size === 3 && (
                   <span className="text-xs text-amber-600 dark:text-amber-400">
                     Maximum 3 parts selected
                   </span>
                 )}
                 <button
                   onClick={handleExplainSelected}
                   disabled={selectedAltIds.size === 0 || advisorLoading || isLocked}
                   title={isLocked ? 'Unlock to use AI Advisor' : undefined}
                   className="rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:cursor-not-allowed disabled:opacity-40"
                 >
                   {advisorLoading ? (
                     <span className="flex items-center gap-1">
                       <span className="h-3 w-3 animate-spin rounded-full border border-white border-t-transparent" />
                       Thinking…
                     </span>
                   ) : (
                     `🤖 Explain Selected (${selectedAltIds.size}/3)`
                   )}
                 </button>
               </div>
            </div>

            {/* AI Advisor response panel - moved above tiles */}
            {advisorResults.length > 0 && (
              <div className="mb-4 space-y-3">
                {advisorResults.map((result, idx) => (
                  <AdvisorResultCard key={idx} result={result} />
                ))}
              </div>
            )}

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {alternatives.map((alt) => (
                <AlternativeCard
                  key={alt.id}
                  alt={alt}
                  isSwapping={swapMutation.isPending && swapConfirm?.id === alt.id}
                  isLocked={isLocked}
                  onSwap={() => setSwapConfirm(alt)}
                  isSelected={selectedAltIds.has(alt.id)}
                  onToggleSelect={() => toggleAlt(alt.id)}
                />
              ))}
            </div>
          </>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Section 3 — Substitution history (collapsible)                      */}
      {/* ------------------------------------------------------------------ */}
      <div className="mt-10">
        <button
          onClick={() => setShowHistory((v) => !v)}
          className="flex items-center gap-2 text-sm font-medium text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
        >
          <span className="transition-transform" style={{ display: 'inline-block', transform: showHistory ? 'rotate(90deg)' : 'rotate(0deg)' }}>
            ▶
          </span>
          Show history
          {history && history.length > 0 && (
            <span className="rounded-full bg-gray-200 px-2 py-0.5 text-xs text-gray-600 dark:bg-gray-700 dark:text-gray-400">
              {history.length}
            </span>
          )}
        </button>

        {showHistory && (
          <div className="mt-3">
            {!history || history.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500">No swaps recorded.</p>
            ) : (
              <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400">
                      <th className="px-4 py-3">Date</th>
                      <th className="px-4 py-3">From MPN</th>
                      <th className="px-4 py-3">To MPN</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                    {history.map((entry) => (
                      <HistoryRow key={entry.id} entry={entry} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {/* Lock toast popup */}
        {lockToast && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setLockToast(null)}>
            <div
              className="rounded-xl bg-white p-5 text-sm text-gray-900 shadow-xl dark:bg-gray-800 dark:text-gray-100"
              onClick={(e) => e.stopPropagation()}
            >
              <p className="mb-4 font-medium">🔒 This BOM line is locked.</p>
              <p className="mb-4 text-gray-500 dark:text-gray-400">
                Unlock it before you {lockToast}.
              </p>
              <button
                onClick={() => setLockToast(null)}
                className="w-full rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700"
              >
                OK
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------

interface ResultRowProps {
  result: PartResult
  isSelected: boolean
  isSelecting: boolean
  isLocked: boolean
  onLockedClick: () => void
  onSelect: () => void
}

function ResultRow({ result, isSelected, isSelecting, isLocked, onLockedClick, onSelect }: ResultRowProps) {
  function handleClick() {
    if (isLocked) {
      onLockedClick()
      return
    }
    onSelect()
  }
  return (
    <tr className={`hover:bg-gray-50 dark:hover:bg-gray-700/40 ${isSelected ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}>
      <td className="px-4 py-2.5">
        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-400">
          #{result.rank}
        </span>
      </td>
      <td className="px-4 py-2.5 font-mono text-xs font-semibold text-gray-900 dark:text-gray-100">
        {result.mpn}
        {isSelected && (
          <span className="ml-2 rounded-full bg-blue-100 px-1.5 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/40 dark:text-blue-400">
            ✓
          </span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs text-gray-700 dark:text-gray-300">{result.manufacturer}</td>
      <td className="px-4 py-2.5 max-w-xs text-xs text-gray-500 dark:text-gray-400">
        {result.description ? (
          <span className="line-clamp-2">{result.description}</span>
        ) : (
          <span className="text-gray-300 dark:text-gray-600">—</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs text-gray-700 dark:text-gray-300">
        {result.distributor ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700 dark:text-gray-300">
        {result.stock.toLocaleString()}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700 dark:text-gray-300">
        {result.unit_price != null ? (
          `$${result.unit_price.toFixed(4)}`
        ) : (
          <span className="text-gray-300 dark:text-gray-600">—</span>
        )}
      </td>
      <td className="px-4 py-2.5 text-xs">
        {result.datasheet_url ? (
          <a
            href={result.datasheet_url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline dark:text-blue-400"
          >
            View ↗
          </a>
        ) : (
          <span className="text-gray-300 dark:text-gray-600">—</span>
        )}
      </td>
      <td className="px-4 py-2.5">
        <button
          onClick={handleClick}
          disabled={isSelected || isSelecting || isLocked}
          title={isLocked ? '🔒 Unlock to make changes' : undefined}
          className={`rounded-lg px-3 py-1 text-xs font-medium transition ${
            isSelected
              ? 'cursor-default bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400'
              : isLocked
                ? 'cursor-not-allowed bg-gray-200 text-gray-400 dark:bg-gray-700 dark:text-gray-500'
                : 'bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-60'
          }`}
        >
          {isSelecting ? 'Selecting…' : isSelected ? '✓ Selected' : 'Select'}
        </button>
      </td>
    </tr>
  )
}

interface AlternativeCardProps {
  alt: PartAlternative
  isSwapping: boolean
  isLocked: boolean
  onSwap: () => void
  isSelected?: boolean
  onToggleSelect?: () => void
}

function AlternativeCard({ alt, isSwapping, isLocked, onSwap, isSelected, onToggleSelect }: AlternativeCardProps) {
  return (
    <div className="flex flex-col rounded-xl bg-white p-4 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      {/* MPN + score + checkbox */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          {onToggleSelect && (
            <input
              type="checkbox"
              checked={isSelected ?? false}
              onChange={onToggleSelect}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-purple-600 focus:ring-purple-500 dark:border-gray-600"
            />
          )}
          <span className="font-mono text-xs font-semibold text-gray-900 break-all dark:text-gray-100">
            {alt.mpn}
          </span>
        </div>
        {alt.match_score != null && (
          <span className="shrink-0 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700 dark:bg-green-900/30 dark:text-green-400">
            {Math.round(alt.match_score * 100)}%
          </span>
        )}
      </div>

      {/* Manufacturer */}
      {alt.manufacturer && (
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">{alt.manufacturer}</p>
      )}

      {/* Description */}
      {alt.description && (
        <p className="mt-1 line-clamp-2 text-xs text-gray-400 dark:text-gray-500">{alt.description}</p>
      )}

      {/* Details tiles */}
      <div className="mt-2 grid grid-cols-2 gap-2">
        {/* Package */}
        <div className="rounded-lg bg-gray-50 px-2 py-1.5 dark:bg-gray-700/50">
          <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">Package</p>
          <p className="text-xs text-gray-700 dark:text-gray-300">
            {alt.package ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
          </p>
        </div>

        {/* Stock */}
        <div className="rounded-lg bg-gray-50 px-2 py-1.5 dark:bg-gray-700/50">
          <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">Stock</p>
          <p className="text-xs text-gray-700 dark:text-gray-300">
            {alt.stock != null ? alt.stock.toLocaleString() : <span className="text-gray-300 dark:text-gray-600">—</span>}
          </p>
        </div>

        {/* Distributor */}
        <div className="rounded-lg bg-gray-50 px-2 py-1.5 dark:bg-gray-700/50">
          <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">Distributor</p>
          <p className="text-xs text-gray-700 dark:text-gray-300">
            {alt.distributor ?? <span className="text-gray-300 dark:text-gray-600">—</span>}
          </p>
        </div>

        {/* Source */}
        <div className="rounded-lg bg-gray-50 px-2 py-1.5 dark:bg-gray-700/50">
          <p className="text-[10px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">Source</p>
          <p className="text-xs text-gray-700 dark:text-gray-300">{alt.source}</p>
        </div>
      </div>

      {/* Datasheet */}
      {alt.datasheet_url ? (
        <a
          href={alt.datasheet_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          Datasheet ↗
        </a>
      ) : (
        <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">No datasheet available</p>
      )}

      {/* Actions */}
      <div className="mt-auto pt-3 flex flex-col gap-2">
        <button
          onClick={onSwap}
          disabled={isSwapping || isLocked}
          title={isLocked ? 'Unlock this part to swap it.' : undefined}
          className="w-full rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isSwapping ? 'Swapping…' : 'Swap to this part'}
        </button>
        {/* v2 hook — not yet functional */}
        <button
          disabled
          title="Coming in a future version"
          className="w-full cursor-not-allowed rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-400 dark:bg-gray-700 dark:text-gray-500"
        >
          Set as preferred distributor
        </button>
      </div>
    </div>
  )
}

function HistoryRow({ entry }: { entry: SubstitutionHistoryEntry }) {
  return (
    <tr className="hover:bg-gray-50 dark:hover:bg-gray-700/40">
      <td className="px-4 py-2.5 text-xs text-gray-500 dark:text-gray-400">{formatDate(entry.swapped_at)}</td>
      <td className="px-4 py-2.5 font-mono text-xs text-gray-500 dark:text-gray-400">
        {entry.from_mpn ?? <span className="italic text-gray-300 dark:text-gray-600">none</span>}
      </td>
      <td className="px-4 py-2.5 font-mono text-xs font-medium text-gray-900 dark:text-gray-100">
        {entry.to_mpn}
      </td>
    </tr>
  )
}

// ---------------------------------------------------------------------------
// AI Advisor Result Card
// ---------------------------------------------------------------------------

function AdvisorResultCard({ result }: { result: AiAdvisorResult & { timestamp: string } }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    const text = `${result.explanation}\n\nRecommendation: ${result.recommendation}\n${result.reasoning}`
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  function formatExplanation(text: string) {
    // Split by sentences (period + space or newline) to create readable paragraphs
    // First try splitting by double newlines, then by sentence boundaries
    const paragraphs = text.split(/\n\n+/)
    if (paragraphs.length > 1) {
      return paragraphs
        .filter((p) => p.trim())
        .map((p, i) => (
          <p key={i} className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
            {p.trim()}
          </p>
        ))
    }
    // Single paragraph - split by sentence boundaries for readability
    const sentences = text.split(/(?<=[.!?])\s+/)
    if (sentences.length > 1) {
      return (
        <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">
          {sentences.map((s, i) => (
            <span key={i}>
              {s}
              {i < sentences.length - 1 && <br />}
            </span>
          ))}
        </p>
      )
    }
    return <p className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed">{text}</p>
  }

  const timeStr = new Date(result.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const comparingTitle = result.mpns && result.mpns.length > 0
    ? `Comparing ${result.mpns.join(', ')}...`
    : null

  return (
    <div className="rounded-xl border border-purple-200 bg-purple-50 px-4 py-3 text-sm dark:border-purple-800 dark:bg-purple-900/20">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-purple-700 dark:text-purple-400">
            {result.cached ? '⚡ Cached' : '🤖 AI Advisor'}
          </span>
          {result.quota_exceeded && (
            <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 dark:bg-red-900/30 dark:text-red-400">
              Quota exceeded
            </span>
          )}
          <span className="text-xs text-gray-400 dark:text-gray-500">{timeStr}</span>
        </div>
        <div className="flex items-center gap-2">
          {result.budget.remaining != null && (
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {result.budget.remaining} queries left
            </span>
          )}
          <button
            onClick={handleCopy}
            className="rounded-md px-2 py-1 text-xs text-purple-600 hover:bg-purple-100 dark:text-purple-400 dark:hover:bg-purple-800/30"
          >
            {copied ? '✓ Copied' : 'Copy'}
          </button>
        </div>
      </div>
      {comparingTitle && (
        <p className="mb-2 text-xs font-semibold text-purple-600 dark:text-purple-400">
          {comparingTitle}
        </p>
      )}
      {result.quota_exceeded ? (
        <p className="text-red-600 dark:text-red-400">{result.explanation}</p>
      ) : (
        <div className="space-y-3">
          <div className="text-sm text-gray-700 dark:text-gray-300 leading-relaxed space-y-2">
            {formatExplanation(result.explanation)}
          </div>
          {result.recommendation && (
            <div className="rounded-lg bg-purple-100 px-3 py-2 dark:bg-purple-900/30">
              <p className="text-xs font-semibold text-purple-700 dark:text-purple-400">
                Recommendation: {result.recommendation}
              </p>
              {result.reasoning && (
                <p className="mt-1 text-xs text-purple-600 dark:text-purple-400">{result.reasoning}</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
