import { useState, useMemo, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getBomLine, manualSearch, swapPart } from '../api/bom'
import type { PartResult } from '../types'

const PROVIDERS = ['DigiKey', 'Mouser', 'Nexar', 'OEMSecrets', 'FindChips']

/** Split a string like "Resistor_SMD:R_0402_1005Metric" into tokens.
 *  Splits on: _, :, -, /, space, and camelCase boundaries. */
function tokenize(text: string): string[] {
  if (!text || text.trim().length === 0) return []
  // First split on common delimiters
  const parts = text.split(/[_:\-/.\s]+/).filter(Boolean)
  // Then split each part on camelCase boundaries
  const tokens: string[] = []
  for (const part of parts) {
    // Insert space before uppercase letters that follow lowercase/digit and precede lowercase
    const camelSplit = part.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    tokens.push(...camelSplit.split(/\s+/).filter(Boolean))
  }
  return tokens
}

interface SearchChipsProps {
  tokens: string[]
  onChipClick: (token: string) => void
  query: string
}

function SearchChips({ tokens, onChipClick, query }: SearchChipsProps) {
  const queryTokens = useMemo(() => {
    return new Set(
      query.split(/\s+/).filter(Boolean).map(t => t.toLowerCase())
    )
  }, [query])

  // Remove tokens already in query + duplicates
  const filteredTokens = useMemo(() => {
    const seen = new Set<string>()
    return tokens.filter(token => {
      const lower = token.toLowerCase()
      if (queryTokens.has(lower) || seen.has(lower)) return false
      seen.add(lower)
      return true
    })
  }, [tokens, queryTokens])

  if (filteredTokens.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5 mt-1">
      {filteredTokens.map(token => (
        <button
          key={token}
          onClick={() => onChipClick(token)}
          className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-blue-300/50 hover:bg-blue-100 hover:ring-blue-400 dark:bg-blue-900/30 dark:text-blue-300 dark:ring-blue-700/50 dark:hover:bg-blue-900/50 dark:hover:ring-blue-600"
          title={`Add "${token}" to search`}
        >
          +{token}
        </button>
      ))}
    </div>
  )
}

export function ManualSearchPage() {
  const { id, lineId } = useParams<{ id: string; lineId: string }>()
  const projectId = Number(id)
  const bomLineId = Number(lineId)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [query, setQuery] = useState('')
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null)
  const [results, setResults] = useState<PartResult[]>([])
  const [providerError, setProviderError] = useState(false)
  const [selectedForAssign, setSelectedForAssign] = useState<PartResult | null>(null)

  // Fetch BOM line details
  const { data: bomLine, isLoading: lineLoading } = useQuery({
    queryKey: ['bomLine', projectId, bomLineId],
    queryFn: () => getBomLine(projectId, bomLineId),
    enabled: !isNaN(projectId) && !isNaN(bomLineId),
  })

  const handleChipClick = useCallback((token: string) => {
    setQuery(prev => {
      const trimmed = prev.trim()
      return trimmed ? `${trimmed} ${token}` : token
    })
  }, [])

  const searchMutation = useMutation({
    mutationFn: ({ q, provider }: { q: string; provider: string | null }) =>
      manualSearch(projectId, bomLineId, q, provider),
    onSuccess: (data) => {
      setResults(data.results)
      setProviderError(data.provider_error)
    },
  })

  const swapMutation = useMutation({
    mutationFn: (result: PartResult) =>
      swapPart(projectId, bomLineId, result.mpn, result.manufacturer),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      queryClient.invalidateQueries({ queryKey: ['partResults', projectId, bomLineId] })
      navigate(`/projects/${projectId}`)
    },
  })

  function handleSearch() {
    if (!query.trim()) return
    setResults([])
    setProviderError(false)
    searchMutation.mutate({ q: query.trim(), provider: selectedProvider })
  }

  function handleSelect(result: PartResult) {
    setSelectedForAssign(result)
  }

  function handleConfirmAssign() {
    if (!selectedForAssign) return
    swapMutation.mutate(selectedForAssign)
  }


  return (
    <div>
      {/* Back button */}
      <button
        onClick={() => navigate(-1)}
        className="mb-4 inline-flex items-center gap-1 text-sm text-blue-600 hover:underline dark:text-blue-400"
      >
        ← Back
      </button>

      <h1 className="mb-6 text-2xl font-semibold text-gray-900 dark:text-gray-100">Manual Component Search</h1>

      {/* BOM Line Details Card */}
      {lineLoading ? (
        <div className="mb-6 rounded-xl border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="h-5 w-32 animate-pulse rounded bg-gray-200 dark:bg-gray-700" />
          <div className="mt-3 grid gap-2 sm:grid-cols-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 w-full animate-pulse rounded bg-gray-100 dark:bg-gray-700" />
            ))}
          </div>
        </div>
      ) : bomLine ? (
        <div className="mb-6 overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          <div className="border-b border-gray-200 bg-gray-50 px-4 py-3 dark:border-gray-700 dark:bg-gray-900/50">
            <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">BOM Line Details</h2>
          </div>
          <div className="grid grid-cols-1 gap-x-6 gap-y-3 p-4 sm:grid-cols-2">
            {bomLine.reference && (
              <DetailField label="Reference" value={bomLine.reference} />
            )}
            {bomLine.value && (
              <DetailField label="Value" value={bomLine.value}>
                <SearchChips tokens={tokenize(bomLine.value)} onChipClick={handleChipClick} query={query} />
              </DetailField>
            )}
            {bomLine.footprint && (
              <DetailField label="Footprint" value={bomLine.footprint}>
                <SearchChips tokens={tokenize(bomLine.footprint)} onChipClick={handleChipClick} query={query} />
              </DetailField>
            )}
            {bomLine.mpn_raw && (
              <DetailField label="MPN" value={bomLine.mpn_raw} />
            )}
            {bomLine.description && (
              <DetailField label="Description" value={bomLine.description} />
            )}
            {bomLine.quantity != null && (
              <DetailField label="Quantity" value={String(bomLine.quantity)} />
            )}
            {bomLine.notes && (
              <DetailField label="Notes" value={bomLine.notes} />
            )}
          </div>
        </div>
      ) : null}

      {/* Search bar */}
      <div className="mb-4 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="Search by MPN, keyword, or description…"
          className="flex-1 rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
        />
        <button
          onClick={handleSearch}
          disabled={searchMutation.isPending || !query.trim()}
          className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {searchMutation.isPending ? 'Searching…' : 'Search'}
        </button>
      </div>

      {/* Provider filter chips */}
      <div className="mb-6 flex flex-wrap gap-2">
        <button
          onClick={() => setSelectedProvider(null)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition ${
            selectedProvider === null
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
          }`}
        >
          All Providers
        </button>
        {PROVIDERS.map((p) => (
          <button
            key={p}
            onClick={() => setSelectedProvider(p)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition ${
              selectedProvider === p
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Provider warning */}
      {providerError && (
        <div className="mb-4 rounded-xl border border-yellow-300 bg-yellow-50 px-4 py-3 text-sm text-yellow-800 dark:border-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-300">
          One or more providers returned errors. Results may be incomplete.
        </div>
      )}


      {/* Confirmation overlay */}
      {selectedForAssign && (
        <div className="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-4 text-sm dark:border-blue-800 dark:bg-blue-900/20">
          <p className="font-medium text-blue-900 dark:text-blue-300">
            Assign{' '}
            <span className="font-mono">{selectedForAssign.mpn}</span>
            {' '}({selectedForAssign.manufacturer}){''}
            to this BOM line?
          </p>
          <div className="mt-3 flex gap-2">
            <button
              onClick={handleConfirmAssign}
              disabled={swapMutation.isPending}
              className="rounded-lg bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {swapMutation.isPending ? 'Assigning…' : 'Confirm'}
            </button>
            <button
              onClick={() => setSelectedForAssign(null)}
              disabled={swapMutation.isPending}
              className="rounded-lg bg-white px-4 py-1.5 text-xs font-medium text-gray-700 ring-1 ring-gray-300 hover:bg-gray-50 disabled:opacity-60 dark:bg-gray-700 dark:text-gray-300 dark:ring-gray-600 dark:hover:bg-gray-600"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Results table */}
      {!results.length && !searchMutation.isPending ? (
        <div className="rounded-xl border-2 border-dashed border-gray-200 py-16 text-center dark:border-gray-700">
          <p className="text-gray-500 dark:text-gray-400">No results yet. Search for a component above.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400">
                  <th className="px-4 py-3">MPN</th>
                  <th className="px-4 py-3">Manufacturer</th>
                  <th className="px-4 py-3">Description</th>
                  <th className="px-4 py-3">Distributor</th>
                  <th className="px-4 py-3 text-right">Stock</th>
                  <th className="px-4 py-3 text-right">Unit Price</th>
                  <th className="px-4 py-3">Datasheet</th>
                  <th className="px-4 py-3">Provider</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {results.map((result) => (
                <tr
                  key={result.id}
                  className={`hover:bg-gray-50 dark:hover:bg-gray-700/40 ${
                    selectedForAssign?.id === result.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                  }`}
                >
                  <td className="px-4 py-2.5 font-mono text-xs font-semibold text-gray-900 dark:text-gray-100">
                    {result.mpn}
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
                   <td className="px-4 py-2.5 text-xs text-gray-500 dark:text-gray-400">
                     {result.source_provider}
                   </td>
                  <td className="px-4 py-2.5">
                    <button
                   onClick={() => handleSelect(result)}
                   disabled={swapMutation.isPending}
                      className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                    >
                      {selectedForAssign?.id === result.id ? 'Selected' : 'Select'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-gray-200 px-4 py-2 text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500">
            {results.length} {results.length === 1 ? 'result' : 'results'}
          </div>
        </div>
      )}
    </div>
  )
}

// Helper component for detail fields
function DetailField({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="overflow-hidden">
      <div className="text-xs font-medium text-gray-500 dark:text-gray-400">{label}</div>
      <div className="mt-0.5 text-sm text-gray-900 dark:text-gray-100 truncate" title={value}>
        {value}
      </div>
      {children}
    </div>
  )
}