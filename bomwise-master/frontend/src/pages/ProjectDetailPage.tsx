import { useState, useEffect, useMemo, useRef } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as XLSX from 'xlsx'
import {
  fetchBomLines,
  matchProject,
  patchBomLine,
  lockBomLine,
  unlockBomLine,
  lockAllBomLines,
  unlockAllBomLines,
  downloadManufacturerBom,
  runNlQuery,
  fetchAiAssistBudget,
  runAiAssist,
  splitBomLine,
  type AiAssistResult,
  type BomLinePatch,
  type NlFilter,
  type NlPreset,
  type NlQueryResult,
  NL_PRESETS,
  mergeNLPresets,
} from '../api/bom'
import { useDebounce } from '../hooks/useDebounce'
import { fetchCapabilities } from '../api/capabilities'
import { fetchProjectFlags, acknowledgeFlag } from '../api/flags'
import {
  fetchProjectPreferences,
  fetchUserPreferences,
  updateProjectPreferences,
  updateUserPreferences,
} from '../api/preferences'
import { cloneProject, fetchProject } from '../api/projects'
import { ConfidenceIndicator, rowBgClass } from '../components/ConfidenceIndicator'
import { CsvImport } from '../components/CsvImport'
import type { BomLine, PartFlag, NlPreset as NlPresetType } from '../types'

// ---------------------------------------------------------------------------
// Constants shared between preferences panels
// ---------------------------------------------------------------------------

const CURRENCIES = [
  'USD', 'EUR', 'GBP', 'AUD', 'CAD', 'JPY', 'CNY', 'SGD',
  'INR', 'BRL', 'MXN', 'CHF', 'HKD', 'NZD', 'SEK', 'NOK', 'DKK',
]

const DISTRIBUTORS = [
  'DigiKey', 'Mouser', 'Arrow', 'Avnet', 'Newark', 'RS Components',
  'Farnell', 'TTI', 'TME', 'LCSC', 'Allied Electronics', 'Future Electronics',
  'NextPCB',
]

// ---------------------------------------------------------------------------
// Sorting helpers (UIF-009 / UIF-010)
// ---------------------------------------------------------------------------

const REF_GROUP: Record<string, number> = {
  U: 0, C: 1, R: 2, L: 3, D: 4, Q: 5, J: 6, Y: 7,
}

function refGroup(ref: string | null): number {
  if (!ref) return 8
  return REF_GROUP[ref.charAt(0).toUpperCase()] ?? 8
}

function defaultSort(a: BomLine, b: BomLine): number {
  const ga = refGroup(a.reference)
  const gb = refGroup(b.reference)
  if (ga !== gb) return ga - gb
  return (a.reference ?? '').localeCompare(b.reference ?? '')
}

type SortField = 'ref' | 'qty'
type SortDir = 'asc' | 'desc' | 'default'

// ---------------------------------------------------------------------------
// ProjectDetailPage
// ---------------------------------------------------------------------------

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: project, isPending: projectPending, isError: projectError } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => fetchProject(projectId),
    enabled: !isNaN(projectId),
  })

  const { data: lines, isPending: linesPending } = useQuery({
    queryKey: ['bom', projectId],
    queryFn: () => fetchBomLines(projectId),
    enabled: !isNaN(projectId),
  })

  const { data: capabilities } = useQuery({
    queryKey: ['capabilities'],
    queryFn: fetchCapabilities,
    staleTime: Infinity,
  })

  const { data: flags } = useQuery({
    queryKey: ['flags', projectId],
    queryFn: () => fetchProjectFlags(projectId),
    enabled: !isNaN(projectId),
  })

  const { data: userPrefs } = useQuery({
    queryKey: ['userPreferences'],
    queryFn: fetchUserPreferences,
  })

  const { data: projectPrefs } = useQuery({
    queryKey: ['projectPreferences', projectId],
    queryFn: () => fetchProjectPreferences(projectId),
    enabled: !isNaN(projectId),
  })

  const matchMutation = useMutation({
    mutationFn: () => matchProject(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  const { data: aiAssistBudget, refetch: refetchBudget } = useQuery({
    queryKey: ['aiAssistBudget', projectId],
    queryFn: () => fetchAiAssistBudget(projectId),
    enabled: !isNaN(projectId),
    staleTime: 30_000,
  })

  const [aiAssistResult, setAiAssistResult] = useState<AiAssistResult | null>(null)
  const aiAssistMutation = useMutation({
    mutationFn: () => runAiAssist(projectId),
    onSuccess: (result) => {
      setAiAssistResult(result)
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      refetchBudget()
    },
  })

  const cloneMutation = useMutation({
    mutationFn: () => cloneProject(projectId),
    onSuccess: (newProject) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${newProject.id}`)
    },
  })

  if (projectPending) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (projectError || !project) {
    return (
      <div className="py-8 text-center">
        <p className="text-red-600">Project not found.</p>
        <Link to="/projects" className="mt-2 block text-sm text-blue-600 hover:underline">
          ← Back to projects
        </Link>
      </div>
    )
  }

  const effectiveCurrency =
    projectPrefs?.preferred_currency ??
    userPrefs?.preferred_currency ??
    'USD'

  const flagByResultId = new Map<number, PartFlag>()
  flags?.forEach((f) => flagByResultId.set(f.part_result_id, f))

  const hasMatches = lines?.some((l) => l.match_type !== null) ?? false

  return (
    <div>
      {/* Breadcrumb */}
      <nav className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        <Link to="/projects" className="hover:text-blue-600 dark:hover:text-blue-400">Projects</Link>
        <span className="mx-2">/</span>
        <span className="text-gray-900 dark:text-gray-100">{project.name}</span>
      </nav>

      {/* Header */}
      <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">{project.name}</h1>
          {project.description && (
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{project.description}</p>
          )}
          {project.variant_tag && (
            <span className="mt-2 inline-block rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-500 dark:bg-gray-700 dark:text-gray-400">
              {project.variant_tag}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => cloneMutation.mutate()}
            disabled={cloneMutation.isPending}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            {cloneMutation.isPending ? 'Cloning…' : 'Clone project'}
          </button>
          <CsvImport projectId={projectId} />
        </div>
      </div>

      {/* Project settings panel */}
      <ProjectSettingsPanel
        projectId={projectId}
        projectPrefs={projectPrefs ?? null}
        userPrefs={userPrefs ?? null}
      />

      {/* BOM section */}
      <div className="mt-6">
        {linesPending ? (
          <div className="flex justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          </div>
        ) : !lines || lines.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-gray-200 py-16 text-center dark:border-gray-700">
            <p className="text-gray-500 dark:text-gray-400">No BOM lines yet.</p>
            <p className="mt-1 text-sm text-gray-400 dark:text-gray-500">Import a CSV file to populate the BOM.</p>
          </div>
        ) : (
          <BomTable
            lines={lines}
            projectId={projectId}
            currency={effectiveCurrency}
            flagByResultId={flagByResultId}
            showLifecycle={capabilities?.has_lifecycle_status ?? false}
            showDatasheet={capabilities?.has_datasheet_urls ?? false}
            hasMatches={hasMatches}
            isMatching={matchMutation.isPending}
            onMatch={() => matchMutation.mutate()}
            aiAssistBudget={aiAssistBudget ?? null}
            isAiAssisting={aiAssistMutation.isPending}
            aiAssistResult={aiAssistResult}
            onAiAssist={() => { setAiAssistResult(null); aiAssistMutation.mutate() }}
            userPrefs={userPrefs ?? null}
          />
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Project Settings Panel
// ---------------------------------------------------------------------------

interface ProjectSettingsPanelProps {
  projectId: number
  projectPrefs: { preferred_currency: string | null; preferred_distributors: string[] | null } | null
  userPrefs: { preferred_currency: string; preferred_distributors: string[] } | null
}

function ProjectSettingsPanel({ projectId, projectPrefs, userPrefs }: ProjectSettingsPanelProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [currency, setCurrency] = useState('')
  const [selectedDist, setSelectedDist] = useState<string[]>([])
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (projectPrefs) {
      setCurrency(projectPrefs.preferred_currency ?? '')
      setSelectedDist(projectPrefs.preferred_distributors ?? [])
    }
  }, [projectPrefs])

  function toggleDist(name: string) {
    setSelectedDist((prev) =>
      prev.includes(name) ? prev.filter((d) => d !== name) : [...prev, name]
    )
  }

  const mutation = useMutation({
    mutationFn: () =>
      updateProjectPreferences(projectId, {
        preferred_currency: currency || null,
        preferred_distributors: selectedDist.length ? selectedDist : null,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['projectPreferences', projectId], updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const inheritedCurrency = userPrefs?.preferred_currency ?? 'USD'
  const inheritedDist = userPrefs?.preferred_distributors?.join(', ') || 'None'

  return (
    <div className="rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Project Settings</span>
        <span className="text-gray-400 dark:text-gray-500">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-4 py-4 dark:border-gray-700">
          <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
            Override global preferences for this project. Leave blank / unchecked to inherit.
          </p>

          <div className="grid gap-6 sm:grid-cols-2">
            {/* Currency */}
            <div>
              <label htmlFor="proj-currency" className="block text-xs font-medium text-gray-600 dark:text-gray-400">
                Currency override
              </label>
              <select
                id="proj-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
                className="mt-1 block w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100"
              >
                <option value="">— Inherit ({inheritedCurrency})</option>
                {CURRENCIES.map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              {projectPrefs?.preferred_currency ? (
                <p className="mt-0.5 text-xs font-medium text-blue-600 dark:text-blue-400">
                  Overriding: {projectPrefs.preferred_currency}
                </p>
              ) : (
                <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">Inheriting: {inheritedCurrency}</p>
              )}
            </div>

            {/* Distributors */}
            <div>
              <p className="block text-xs font-medium text-gray-600 dark:text-gray-400">Distributor override</p>
              <p className="mt-0.5 mb-2 text-xs text-gray-400 dark:text-gray-500">
                Uncheck all to inherit ({inheritedDist}).
              </p>
              <div className="grid grid-cols-2 gap-1">
                {DISTRIBUTORS.map((d) => (
                  <label key={d} className="flex items-center gap-1.5 text-xs text-gray-700 cursor-pointer dark:text-gray-300">
                    <input
                      type="checkbox"
                      checked={selectedDist.includes(d)}
                      onChange={() => toggleDist(d)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 dark:border-gray-600"
                    />
                    {d}
                  </label>
                ))}
              </div>
              {projectPrefs?.preferred_distributors?.length ? (
                <p className="mt-1 text-xs font-medium text-blue-600 dark:text-blue-400">
                  Overriding: {projectPrefs.preferred_distributors.join(', ')}
                </p>
              ) : (
                <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">Inheriting: {inheritedDist}</p>
              )}
            </div>
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={() => mutation.mutate()}
              disabled={mutation.isPending}
              className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {mutation.isPending ? 'Saving…' : 'Save'}
            </button>
            {saved && <span className="text-xs text-green-600 dark:text-green-400">✓ Saved</span>}
            {mutation.isError && <span className="text-xs text-red-600 dark:text-red-400">Failed</span>}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Editable cell (UIF-008)
// ---------------------------------------------------------------------------

interface EditableCellProps {
  value: string | number | null
  type?: 'text' | 'number' | 'url'
  multiline?: boolean
  placeholder?: string
  className?: string
  onSave: (val: string) => void
}

function EditableCell({
  value,
  type = 'text',
  multiline = false,
  placeholder,
  className = '',
  onSave,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(value ?? ''))
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  // Keep draft in sync when value changes from outside (e.g. query invalidation)
  useEffect(() => {
    if (!editing) setDraft(String(value ?? ''))
  }, [value, editing])

  function commit() {
    onSave(draft)
    setEditing(false)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !multiline) commit()
    if (e.key === 'Escape') { setDraft(String(value ?? '')); setEditing(false) }
  }

  if (editing) {
    const sharedProps = {
      value: draft,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setDraft(e.target.value),
      onBlur: commit,
      onKeyDown: handleKeyDown,
      placeholder,
      className: `w-full rounded border border-blue-400 bg-white px-1 py-0.5 text-xs text-gray-900 focus:outline-none dark:bg-gray-700 dark:text-gray-100 ${className}`,
    }
    return multiline ? (
      <textarea
        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
        rows={2}
        {...sharedProps}
      />
    ) : (
      <input
        ref={inputRef as React.RefObject<HTMLInputElement>}
        type={type}
        {...sharedProps}
      />
    )
  }

  return (
    <span
      onClick={() => { setDraft(String(value ?? '')); setEditing(true) }}
      title="Click to edit"
      className={`cursor-text rounded px-0.5 hover:bg-blue-50 hover:ring-1 hover:ring-blue-200 dark:hover:bg-blue-900/20 dark:hover:ring-blue-700 ${className}`}
    >
      {value !== null && value !== '' ? (
        String(value)
      ) : (
        <span className="text-gray-300 select-none">—</span>
      )}
    </span>
  )
}

// ---------------------------------------------------------------------------
// UIF-016: Column visibility
// ---------------------------------------------------------------------------

type ColKey =
  | 'thumbnail' | 'ref' | 'value' | 'footprint' | 'mpn_raw' | 'qty'
  | 'matched_mpn' | 'manufacturer' | 'source' | 'stock' | 'price'
  | 'status' | 'alerts' | 'notes' | 'lifecycle' | 'datasheet'

interface ColDef { key: ColKey; label: string; defaultVisible: boolean }

const COL_DEFS: ColDef[] = [
  { key: 'thumbnail',    label: 'Image',        defaultVisible: true  },
  { key: 'ref',          label: 'Ref',          defaultVisible: true  },
  { key: 'value',        label: 'Value',        defaultVisible: true  },
  { key: 'footprint',    label: 'Footprint',    defaultVisible: false },
  { key: 'mpn_raw',      label: 'MPN (Raw)',    defaultVisible: true  },
  { key: 'qty',          label: 'Qty',          defaultVisible: true  },
  { key: 'matched_mpn',  label: 'Matched MPN',  defaultVisible: true  },
  { key: 'manufacturer', label: 'Manufacturer', defaultVisible: true  },
  { key: 'source',       label: 'Source',       defaultVisible: true  },
  { key: 'stock',        label: 'Stock',        defaultVisible: true  },
  { key: 'price',        label: 'Price',        defaultVisible: true  },
  { key: 'status',       label: 'Status',       defaultVisible: true  },
  { key: 'alerts',       label: 'Alerts',       defaultVisible: true  },
  { key: 'notes',        label: 'Notes',        defaultVisible: true  },
  { key: 'lifecycle',    label: 'Lifecycle',    defaultVisible: false },
  { key: 'datasheet',    label: 'Datasheet',    defaultVisible: false },
]

const _COL_LS_KEY = 'bomexplorer_col_visibility'

function _loadColVisibility(): Record<ColKey, boolean> {
  const defaults = Object.fromEntries(
    COL_DEFS.map((c) => [c.key, c.defaultVisible])
  ) as Record<ColKey, boolean>
  try {
    const raw = localStorage.getItem(_COL_LS_KEY)
    if (!raw) return defaults
    return { ...defaults, ...(JSON.parse(raw) as Partial<Record<ColKey, boolean>>) }
  } catch {
    return defaults
  }
}

// ---------------------------------------------------------------------------
// NL query filter evaluator
// ---------------------------------------------------------------------------

const _CATEGORY_MAP: Record<string, string> = {
  C: 'capacitor', R: 'resistor', U: 'ic', L: 'inductor',
  D: 'diode', Q: 'transistor', J: 'connector', Y: 'crystal',
}

function _getFieldValue(line: BomLine, field: string): unknown {
  switch (field) {
    case 'reference':   return line.reference ?? null
    case 'value':       return line.value ?? null
    case 'footprint':   return line.footprint ?? null
    case 'mpn_raw':     return line.mpn_raw ?? null
    case 'quantity':    return line.quantity ?? null
    case 'matched_mpn': return line.selected_result?.mpn ?? null
    case 'manufacturer':return line.selected_result?.manufacturer ?? null
    case 'description': return line.selected_result?.description ?? line.description ?? null
    case 'stock':       return line.selected_result?.stock ?? null
    case 'unit_price':  return line.selected_result?.unit_price ?? null
    case 'distributor': return line.selected_result?.distributor ?? null
    case 'match_type':  return line.match_type ?? null
    case 'category': {
      const prefix = (line.reference ?? '').charAt(0).toUpperCase()
      return _CATEGORY_MAP[prefix] ?? null
    }
    case 'notes':             return line.notes ?? null
    case 'locked':            return line.locked
    case 'matched_provider':  return line.matched_provider ?? null
    default:                  return null
  }
}

function _evalOp(fieldVal: unknown, op: string, filterVal: unknown): boolean {
  const fStr = String(fieldVal ?? '').toLowerCase()
  const vStr = String(filterVal ?? '').toLowerCase()
  switch (op) {
    case 'is_null':       return fieldVal === null || fieldVal === undefined
    case 'is_not_null':   return fieldVal !== null && fieldVal !== undefined
    case 'eq':            return fStr === vStr
    case 'neq':           return fStr !== vStr
    case 'lt':            return typeof fieldVal === 'number' && fieldVal < Number(filterVal)
    case 'lte':           return typeof fieldVal === 'number' && fieldVal <= Number(filterVal)
    case 'gt':            return typeof fieldVal === 'number' && fieldVal > Number(filterVal)
    case 'gte':           return typeof fieldVal === 'number' && fieldVal >= Number(filterVal)
    case 'contains':      return fStr.includes(vStr)
    case 'not_contains':  return !fStr.includes(vStr)
    default:              return false
  }
}

function _matchesFilters(line: BomLine, filters: NlFilter[]): boolean {
  return filters.every((f) => _evalOp(_getFieldValue(line, f.field), f.op, f.value))
}

// ---------------------------------------------------------------------------
// BOM Table (UIF-005 through UIF-016)
// ---------------------------------------------------------------------------

interface BomTableProps {
  lines: BomLine[]
  projectId: number
  currency: string
  flagByResultId: Map<number, PartFlag>
  showLifecycle: boolean
  showDatasheet: boolean
  hasMatches: boolean
  isMatching: boolean
  onMatch: () => void
  aiAssistBudget: import('../api/bom').AiAssistBudget | null
  isAiAssisting: boolean
  aiAssistResult: import('../api/bom').AiAssistResult | null
  onAiAssist: () => void
  userPrefs: { preferred_nl_presets: NlPresetType[] } | null
}

function BomTable({
  lines,
  projectId,
  currency,
  flagByResultId,
  showLifecycle,
  showDatasheet,
  hasMatches,
  isMatching,
  onMatch,
  aiAssistBudget,
  isAiAssisting,
  aiAssistResult,
  onAiAssist,
  userPrefs,
}: BomTableProps) {
  const queryClient = useQueryClient()

  // UIF-009 / UIF-010: sort state
  const [sortField, setSortField] = useState<SortField | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>('default')

  // NL query bar
  const [nlInput, setNlInput] = useState('')
  const [nlResult, setNlResult] = useState<NlQueryResult | null>(null)
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const debouncedNl = useDebounce(nlInput, 600)

  // Merge built-in + user custom presets
  const effectivePresets = useMemo(
    () => mergeNLPresets(NL_PRESETS, userPrefs?.preferred_nl_presets || []),
    [userPrefs?.preferred_nl_presets]
  )

  // Priority 1: Restore NL state from sessionStorage on mount
  useEffect(() => {
    try {
      const saved = sessionStorage.getItem(`nl_filter_${projectId}`)
      if (saved) {
        const { nlInput: sInput, nlResult: sResult } = JSON.parse(saved)
        setNlInput(sInput ?? '')
        setNlResult(sResult)
      }
    } catch {
      // ignore corrupt data
    }
  }, [projectId])

  // Priority 1: Save NL state to sessionStorage on every change
  useEffect(() => {
    if (nlInput || nlResult) {
      sessionStorage.setItem(
        `nl_filter_${projectId}`,
        JSON.stringify({ nlInput, nlResult })
      )
    } else {
      sessionStorage.removeItem(`nl_filter_${projectId}`)
    }
  }, [nlInput, nlResult, projectId])

  const nlMutation = useMutation({
    mutationFn: (q: string) => runNlQuery(projectId, q),
    onSuccess: (data) => setNlResult(data),
  })

  // Save NL text as custom preset mutation
  const [savePresetFeedback, setSavePresetFeedback] = useState(false)
  const savePresetMutation = useMutation({
    mutationFn: (presets: NlPresetType[]) => updateUserPreferences({ preferred_nl_presets: presets }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['userPreferences'], updated)
      setSavePresetFeedback(true)
      setTimeout(() => setSavePresetFeedback(false), 1500)
    },
  })

  useEffect(() => {
    if (debouncedNl.trim()) {
      // If text matches a preset label, do NOT call API — preset click handles this
      const isPresetLabel = effectivePresets.some((p) => debouncedNl === p.label || debouncedNl === `⚡ ${p.label}`)
      if (!isPresetLabel) setActivePreset(null)
      else return // preset click sets nlResult with highlightOnly — don't overwrite
      nlMutation.mutate(debouncedNl)
    } else {
      setNlResult(null)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedNl])

  // Preset chip click handler
  function handlePresetClick(preset: NlPreset) {
    const isSame = activePreset === preset.label
    if (isSame) {
      // Toggle off: clear preset
      setNlInput('')
      setNlResult(null)
      setActivePreset(null)
    } else {
      setNlInput(preset.label)
      setNlResult({ filters: preset.filters, highlight_only: preset.highlightOnly || false, explanation: preset.label })
      setActivePreset(preset.label)
    }
  }

  // Save current NL text as custom preset
  function handleSaveAsPreset() {
    const label = nlInput.trim()
    if (!label) return
    const existing = userPrefs?.preferred_nl_presets || []
    if (existing.some((p) => p.label === label)) {
      setSavePresetFeedback(true)
      setTimeout(() => setSavePresetFeedback(false), 1500)
      return
    }
    const next: NlPresetType[] = [...existing, { label, filters: [], highlightOnly: false }]
    savePresetMutation.mutate(next)
  }

  function cycleSort(field: SortField) {
    if (sortField !== field) {
      setSortField(field)
      setSortDir('asc')
    } else if (sortDir === 'asc') {
      setSortDir('desc')
    } else {
      setSortField(null)
      setSortDir('default')
    }
  }

  function resetOrder() {
    setSortField(null)
    setSortDir('default')
  }

  const sortIcon = (field: SortField) => {
    if (sortField !== field) return ' ↕'
    return sortDir === 'asc' ? ' ↑' : ' ↓'
  }

  // Sorted lines
  const sortedLines = useMemo(() => {
    if (sortDir === 'default' || !sortField) {
      return [...lines].sort(defaultSort)
    }
    return [...lines].sort((a, b) => {
      if (sortField === 'ref') {
        const cmp = (a.reference ?? '').localeCompare(b.reference ?? '')
        return sortDir === 'asc' ? cmp : -cmp
      } else {
        const cmp = (a.quantity ?? 0) - (b.quantity ?? 0)
        return sortDir === 'asc' ? cmp : -cmp
      }
    })
  }, [lines, sortField, sortDir])

  // NL query: compute which lines match and which to display
  const nlFilters = nlResult?.filters ?? []
  const nlActive = nlInput.trim() !== '' && nlResult !== null && nlFilters.length > 0
  const nlHighlightOnly = nlResult?.highlight_only ?? false

  const matchedLineIds = useMemo(() => {
    if (!nlActive) return null
    const ids = new Set<number>()
    sortedLines.forEach((l) => { if (_matchesFilters(l, nlFilters)) ids.add(l.id) })
    return ids
  }, [nlActive, sortedLines, nlFilters])

  // Lines to actually render (hide non-matches when not highlight_only)
  const displayLines = useMemo(() => {
    if (!nlActive || nlHighlightOnly) return sortedLines
    return sortedLines.filter((l) => matchedLineIds?.has(l.id))
  }, [nlActive, nlHighlightOnly, sortedLines, matchedLineIds])

  // UIF-011: summary totals
  const totalQty = sortedLines.reduce((sum, l) => sum + (l.quantity ?? 0), 0)
  const totalPrice = sortedLines.reduce((sum, l) => {
    if (l.selected_result?.unit_price == null || l.quantity == null) return sum
    return sum + l.selected_result.unit_price * l.quantity
  }, 0)
  const hasAnyPrice = sortedLines.some(
    (l) => l.selected_result?.unit_price != null && l.quantity != null
  )

  const [exportMenuOpen, setExportMenuOpen] = useState(false)
  const [colMenuOpen, setColMenuOpen] = useState(false)
  const [colVis, setColVis] = useState<Record<ColKey, boolean>>(_loadColVisibility)

  function toggleCol(key: ColKey) {
    setColVis((prev) => {
      const next = { ...prev, [key]: !prev[key] }
      localStorage.setItem(_COL_LS_KEY, JSON.stringify(next))
      return next
    })
  }

  // Returns true when a column should be rendered.
  // Lifecycle / Datasheet additionally require provider support.
  function show(key: ColKey): boolean {
    if (key === 'lifecycle') return colVis.lifecycle && showLifecycle
    if (key === 'datasheet') return colVis.datasheet && showDatasheet
    return colVis[key]
  }

  // Patch mutation
  const patchMutation = useMutation({
    mutationFn: ({ lineId, patch }: { lineId: number; patch: BomLinePatch }) =>
      patchBomLine(projectId, lineId, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  function handlePatch(lineId: number, patch: BomLinePatch) {
    patchMutation.mutate({ lineId, patch })
  }

  // Lock / unlock mutation (per-row)
  const lockMutation = useMutation({
    mutationFn: ({ lineId, locked }: { lineId: number; locked: boolean }) =>
      locked ? lockBomLine(projectId, lineId) : unlockBomLine(projectId, lineId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  // Bulk lock / unlock mutations
  // When NL filter is active, only operate on visible (displayLines) rows.
  const lockAllMutation = useMutation({
    mutationFn: (ids?: number[]) => lockAllBomLines(projectId, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  const unlockAllMutation = useMutation({
    mutationFn: (ids?: number[]) => unlockAllBomLines(projectId, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    },
  })

  const bulkBusy = lockAllMutation.isPending || unlockAllMutation.isPending

  // Row splitter
  const [splitConfirmLine, setSplitConfirmLine] = useState<number | null>(null)
  const splitMutation = useMutation({
    mutationFn: (lineId: number) => splitBomLine(projectId, lineId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
      setSplitConfirmLine(null)
    },
  })

  // Flag acknowledge
  const ackMutation = useMutation({
    mutationFn: (flagId: number) => acknowledgeFlag(flagId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['flags', projectId] })
    },
  })

  // Export helpers
  function exportRows() {
    return sortedLines.map((l) => ({
      Reference: l.reference ?? '',
      Value: l.value ?? '',
      Footprint: l.footprint ?? '',
      MPN: l.selected_result?.mpn ?? l.mpn_raw ?? '',
      Manufacturer: l.selected_result?.manufacturer ?? '',
      Description: l.selected_result?.description ?? l.description ?? '',
      Distributor: l.selected_result?.distributor ?? '',
      'Unit Price': l.selected_result?.unit_price ?? '',
      Currency: currency,
      Stock: l.selected_result?.stock ?? '',
      QTY: l.quantity ?? 1,
      Notes: l.notes ?? '',
    }))
  }

  const EXPORT_HEADERS = [
    'Reference', 'Value', 'Footprint', 'MPN', 'Manufacturer',
    'Description', 'Distributor', 'Unit Price', 'Currency', 'Stock', 'QTY', 'Notes',
  ]

  function exportCsv() {
    const rows = exportRows()
    const summaryRow = {
      Reference: 'TOTAL', Value: '', Footprint: '', MPN: '', Manufacturer: '',
      Description: '', Distributor: '',
      'Unit Price': hasAnyPrice ? totalPrice.toFixed(4) : '',
      Currency: hasAnyPrice ? currency : '',
      Stock: '', QTY: totalQty, Notes: '',
    }
    const allRows = [...rows, summaryRow]
    const csv = [
      EXPORT_HEADERS,
      ...allRows.map((r) =>
        EXPORT_HEADERS.map((h) =>
          `"${String(r[h as keyof typeof r] ?? '').replace(/"/g, '""')}"`
        ).join(',')
      ),
    ].join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'bom_export.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  function exportXlsx() {
    const rows = exportRows()
    const summaryRow = {
      Reference: 'TOTAL', Value: '', Footprint: '', MPN: '', Manufacturer: '',
      Description: '', Distributor: '',
      'Unit Price': hasAnyPrice ? totalPrice : '',
      Currency: hasAnyPrice ? currency : '',
      Stock: '', QTY: totalQty, Notes: '',
    }
    const ws = XLSX.utils.json_to_sheet([...rows, summaryRow], { header: EXPORT_HEADERS })
    const wb = XLSX.utils.book_new()
    XLSX.utils.book_append_sheet(wb, ws, 'BOM')
    XLSX.writeFile(wb, 'bom_export.xlsx')
  }

  return (
    <div>
      {/* NL query bar */}
      <div className="mb-4">
        <div className="relative flex items-center gap-2">
          <div className="relative flex-1">
            <input
              type="text"
              value={nlInput}
              onChange={(e) => setNlInput(e.target.value)}
              placeholder="Ask about your BOM — e.g. 'parts with stock below 100'"
              className="w-full rounded-xl border border-gray-300 bg-white py-2.5 pl-4 pr-10 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500"
            />
            {nlMutation.isPending && (
              <span className="absolute right-10 top-1/2 -translate-y-1/2 flex items-center">
                <span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
              </span>
            )}
            {nlInput && (
              <button
                onClick={() => { setNlInput(''); setNlResult(null); setActivePreset(null) }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-lg leading-none"
                aria-label="Clear"
              >
                ×
              </button>
            )}
          </div>
          {nlInput && (
            <button
              onClick={handleSaveAsPreset}
              disabled={savePresetMutation.isPending || savePresetFeedback}
              title="Save current text as a custom NL preset"
              className="shrink-0 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2.5 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-60 dark:border-amber-700 dark:bg-amber-900/30 dark:text-amber-400 dark:hover:bg-amber-900/50"
            >
              {savePresetMutation.isPending ? (
                'Saving…'
              ) : savePresetFeedback ? (
                '✓ Saved'
              ) : (
                'Save as preset'
              )}
            </button>
          )}
        </div>
        {/* Preset filter chips */}
        <div className="mt-2 flex flex-wrap gap-2">
          {effectivePresets.map((preset) => {
            const isCustom = preset.label.startsWith('⚡ ')
            const isActive = activePreset === preset.label
            const isHighlightOnly = preset.highlightOnly === true
            return (
              <button
                key={preset.label}
                onClick={() => handlePresetClick(preset)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition ${
                  isActive
                    ? isHighlightOnly
                      ? 'bg-purple-600 text-white hover:bg-purple-700'
                      : isCustom
                        ? 'bg-amber-600 text-white hover:bg-amber-700'
                        : 'bg-blue-600 text-white hover:bg-blue-700'
                    : isHighlightOnly
                      ? 'bg-purple-50 text-purple-700 ring-1 ring-purple-300 hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-300 dark:ring-purple-700 dark:hover:bg-purple-900/50'
                      : isCustom
                        ? 'bg-amber-50 text-amber-700 ring-1 ring-amber-300 hover:bg-amber-100 dark:bg-amber-900/30 dark:text-amber-300 dark:ring-amber-700 dark:hover:bg-amber-900/50'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
                }`}
              >
                {preset.label}
              </button>
            )
          })}
        </div>

        {nlResult && (
          <div className="mt-1.5 flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
            <span>{nlResult.explanation}</span>
            {nlActive && (
              <span className="font-medium text-gray-700 dark:text-gray-300">
                {nlHighlightOnly
                  ? `${matchedLineIds?.size ?? 0} of ${sortedLines.length} parts highlighted`
                  : `Showing ${displayLines.length} of ${sortedLines.length} parts`}
              </span>
            )}
            {nlActive && nlFilters.length === 0 && (
              <span className="italic text-gray-400">No filter applied</span>
            )}
          </div>
        )}
      </div>

      {/* Toolbar: Match button + exports */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* UIF-005 */}
          <button
            onClick={onMatch}
            disabled={isMatching}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
          >
            {isMatching ? (
              <span className="flex items-center gap-1.5">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                Matching…
              </span>
            ) : hasMatches ? (
              'Re-match Parts'
            ) : (
              'Match Parts'
            )}
          </button>

          {/* AI Assist button */}
          {(() => {
            const budgetExhausted = aiAssistBudget !== null
              && !aiAssistBudget.unlimited
              && aiAssistBudget.remaining === 0
            const budgetLabel = aiAssistBudget
              ? aiAssistBudget.unlimited
                ? '✨ AI Assist'
                : `✨ AI Assist (${aiAssistBudget.remaining ?? '?'} left)`
              : '✨ AI Assist'
            return (
              <button
                onClick={onAiAssist}
                disabled={isAiAssisting || budgetExhausted}
                title={
                  budgetExhausted
                    ? 'Monthly AI Assist limit reached. Resets on the 1st of next month.'
                    : 'Use AI to classify pending parts and find candidates'
                }
                className="rounded-lg bg-purple-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-purple-700 disabled:opacity-60"
              >
                {isAiAssisting ? (
                  <span className="flex items-center gap-1.5">
                    <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                    AI Assist…
                  </span>
                ) : budgetLabel}
              </button>
            )
          })()}

          {/* AI Assist result summary toast */}
          {aiAssistResult && !isAiAssisting && (
            <span className="rounded-lg bg-purple-50 px-3 py-1.5 text-xs text-purple-700 dark:bg-purple-900/20 dark:text-purple-400">
              AI: {aiAssistResult.ai_suggested} suggested · {aiAssistResult.no_part_needed} no part needed · {aiAssistResult.no_match} no match
              {aiAssistResult.skipped_budget > 0 && ` · ${aiAssistResult.skipped_budget} skipped (budget)`}
            </span>
          )}

          {/* Bulk lock / unlock */}
          {/* When NL filter active → only visible rows; otherwise → all rows */}
          {/* Note: Re-match Parts already skips locked rows — see matching.py match_project filter */}
          <button
            onClick={() => lockAllMutation.mutate(nlActive ? displayLines.map(l => l.id) : undefined)}
            disabled={bulkBusy || isMatching}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            {lockAllMutation.isPending ? (
              <span className="flex items-center gap-1.5">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
                Locking…
              </span>
            ) : nlActive ? `Lock Visible (${displayLines.length})` : 'Lock All'}
          </button>
          <button
            onClick={() => unlockAllMutation.mutate(nlActive ? displayLines.map(l => l.id) : undefined)}
            disabled={bulkBusy || isMatching}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
          >
            {unlockAllMutation.isPending ? (
              <span className="flex items-center gap-1.5">
                <span className="h-3 w-3 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
                Unlocking…
              </span>
            ) : nlActive ? `Unlock Visible (${displayLines.length})` : 'Unlock All'}
          </button>

          {/* UIF-010 Reset order */}
          {(sortField !== null || sortDir !== 'default') && (
            <button
              onClick={resetOrder}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-400 dark:hover:bg-gray-700"
            >
              Reset Order
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* UIF-016: Columns toggle */}
          <div className="relative">
            <button
              onClick={() => setColMenuOpen((v) => !v)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
            >
              Columns ▾
            </button>
            {colMenuOpen && (
              <div
                className="absolute right-0 z-10 mt-1 w-44 rounded-xl border border-gray-200 bg-white py-2 shadow-lg dark:border-gray-700 dark:bg-gray-800"
                onMouseLeave={() => setColMenuOpen(false)}
              >
                {COL_DEFS.filter((c) => {
                  if (c.key === 'lifecycle') return showLifecycle
                  if (c.key === 'datasheet') return showDatasheet
                  return true
                }).map((c) => (
                  <label
                    key={c.key}
                    className="flex cursor-pointer items-center gap-2 px-3 py-1 text-sm text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-700"
                  >
                    <input
                      type="checkbox"
                      checked={colVis[c.key]}
                      onChange={() => toggleCol(c.key)}
                      className="h-3.5 w-3.5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    {c.label}
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="relative">
          <button
            onClick={() => setExportMenuOpen((v) => !v)}
            className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Export ▾
          </button>
          {exportMenuOpen && (
            <div
              className="absolute right-0 z-10 mt-1 w-52 rounded-xl border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-800"
              onMouseLeave={() => setExportMenuOpen(false)}
            >
              <button
                onClick={() => { exportCsv(); setExportMenuOpen(false) }}
                className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 rounded-t-xl dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Raw BOM (CSV)
              </button>
              <button
                onClick={() => { exportXlsx(); setExportMenuOpen(false) }}
                className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Raw BOM (Excel)
              </button>
              <button
                onClick={() => { void downloadManufacturerBom(projectId, 'csv'); setExportMenuOpen(false) }}
                className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Manufacturer BOM (CSV)
              </button>
              <button
                onClick={() => { void downloadManufacturerBom(projectId, 'xlsx'); setExportMenuOpen(false) }}
                className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50 rounded-b-xl dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Manufacturer BOM (Excel)
              </button>
            </div>
          )}
          </div>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-400">
              <th className="px-4 py-3">#</th>
              {show('thumbnail') && <th className="py-3" style={{ width: 48, minWidth: 48 }} />}
              {show('ref') && (
                <th
                  className="cursor-pointer select-none px-4 py-3 hover:text-gray-700"
                  onClick={() => cycleSort('ref')}
                >
                  Ref{sortIcon('ref')}
                </th>
              )}
              {show('value') && <th className="px-4 py-3">Value</th>}
              {show('footprint') && <th className="px-4 py-3">Footprint</th>}
              {show('mpn_raw') && <th className="px-4 py-3">MPN (raw)</th>}
              {show('qty') && (
                <th
                  className="cursor-pointer select-none px-4 py-3 text-right hover:text-gray-700"
                  onClick={() => cycleSort('qty')}
                >
                  Qty{sortIcon('qty')}
                </th>
              )}
              {show('matched_mpn') && <th className="px-4 py-3">Matched MPN</th>}
              {show('manufacturer') && <th className="px-4 py-3">Manufacturer</th>}
              {show('source') && <th className="px-4 py-3">Source</th>}
              {show('stock') && <th className="px-4 py-3 text-right">Stock</th>}
              {show('price') && <th className="px-4 py-3 text-right">Price ({currency})</th>}
              {show('status') && <th className="px-4 py-3">Status</th>}
              {show('alerts') && <th className="px-4 py-3">Alerts</th>}
              {show('notes') && <th className="px-4 py-3">Notes</th>}
              {show('lifecycle') && <th className="px-4 py-3">Lifecycle</th>}
              {show('datasheet') && <th className="px-4 py-3">Datasheet</th>}
              <th className="px-4 py-3" title="Lock / unlock"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {displayLines.map((line, i) => {
              const result = line.selected_result
              const flag = result ? flagByResultId.get(result.id) : undefined
              // Effective datasheet: user-specified on bom_line takes priority
              const datasheetUrl = line.datasheet_url || result?.datasheet_url
              const nlHighlighted = nlActive && nlHighlightOnly && matchedLineIds?.has(line.id)

              const isDnp = line.dnp
              return (
                <tr
                  key={line.id}
                  className={`hover:bg-gray-50 dark:hover:bg-gray-700/40 ${isDnp ? 'opacity-50' : ''} ${rowBgClass(line.match_type, line.locked, !!nlHighlighted)}`}
                  data-nl-highlighted={nlHighlighted || undefined}
                >
                  <td className="px-4 py-2.5 text-gray-400 dark:text-gray-500">{i + 1}</td>

                  {show('thumbnail') && (
                    <td className="py-2" style={{ width: 48, minWidth: 48 }}>
                      {result?.image_url ? (
                        <a href={result.image_url} target="_blank" rel="noreferrer">
                          <img
                            src={result.image_url}
                            alt={result.mpn}
                            style={{ width: 40, height: 40, objectFit: 'contain', borderRadius: 4, border: '1px solid #e5e7eb' }}
                          />
                        </a>
                      ) : (
                        <svg
                          width="24"
                          height="24"
                          viewBox="0 0 24 24"
                          fill="none"
                          xmlns="http://www.w3.org/2000/svg"
                          style={{ color: '#d1d5db', display: 'block', margin: '0 auto' }}
                        >
                          {/* Generic IC/chip outline */}
                          <rect x="6" y="4" width="12" height="16" rx="1" stroke="currentColor" strokeWidth="1.5" />
                          <line x1="9" y1="4" x2="9" y2="2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="12" y1="4" x2="12" y2="2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="15" y1="4" x2="15" y2="2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="9" y1="22" x2="9" y2="20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="12" y1="22" x2="12" y2="20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="15" y1="22" x2="15" y2="20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="6" y1="9" x2="4" y2="9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="6" y1="12" x2="4" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="6" y1="15" x2="4" y2="15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="18" y1="9" x2="20" y2="9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="18" y1="12" x2="20" y2="12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          <line x1="18" y1="15" x2="20" y2="15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                      )}
                    </td>
                  )}

                  {show('ref') && (
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-900 dark:text-gray-100">
                      <span className="flex items-center gap-1.5">
                        <EditableCell
                          value={line.reference}
                          onSave={(v) => handlePatch(line.id, { reference: v || null })}
                        />
                        {isDnp && (
                          <span className="rounded px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-gray-200 text-gray-500 line-through">
                            DNP
                          </span>
                        )}
                        {line.match_type === 'ai_suggested' && (
                          <Link
                            to={`/projects/${projectId}/bom/${line.id}/variants`}
                            className="rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide bg-purple-100 text-purple-700 hover:bg-purple-200 dark:bg-purple-900/30 dark:text-purple-400"
                            title="AI found candidates — click to review and select one"
                          >
                            ✨ AI
                          </Link>
                        )}
                        {line.reference && line.reference.includes(',') && (
                          <button
                            onClick={() => setSplitConfirmLine(line.id)}
                            className="rounded px-1 py-0.5 text-[10px] font-bold tracking-wide bg-blue-100 text-blue-600 hover:bg-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:hover:bg-blue-900/50"
                            title="Split this row into individual references"
                          >
                            ✂ Split
                          </button>
                        )}
                      </span>
                    </td>
                  )}
                  {show('value') && (
                    <td className="px-4 py-2.5 text-gray-900 dark:text-gray-100">
                      {line.value ?? <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('footprint') && (
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-600 dark:text-gray-400">
                      {line.footprint ?? <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('mpn_raw') && (
                    <td className="px-4 py-2.5 font-mono text-xs text-gray-500 dark:text-gray-400">
                      {line.mpn_raw ?? <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('qty') && (
                    <td className="px-4 py-2.5 text-right tabular-nums text-gray-900 dark:text-gray-100">
                      <EditableCell
                        value={line.quantity ?? 1}
                        type="number"
                        className="text-right"
                        onSave={(v) => {
                          const n = parseInt(v, 10)
                          handlePatch(line.id, { quantity: isNaN(n) ? 1 : n })
                        }}
                      />
                    </td>
                  )}
                  {show('matched_mpn') && (
                    <td className="px-4 py-2.5 font-mono text-xs">
                      {result ? (
                        <Link
                          to={`/projects/${projectId}/bom/${line.id}/variants`}
                          className="text-blue-600 hover:underline"
                          title="View all candidates"
                        >
                          {result.mpn}
                        </Link>
                      ) : line.dnp ? (
                        <span className="text-gray-400" title="DNP">—</span>
                      ) : line.locked ? (
                        <span className="flex items-center gap-1.5">
                          <span className="text-gray-400">—</span>
                          <span className="text-[10px] text-gray-300 dark:text-gray-600" title="Unlock this line to enable manual search">
                            🔒 Unlock to search
                          </span>
                        </span>
                      ) : (
                        <span className="flex items-center gap-2">
                          <Link
                            to={`/projects/${projectId}/bom/${line.id}/variants`}
                            className="text-gray-400 hover:text-blue-600"
                            title="View candidates"
                          >
                            —
                          </Link>
                          <Link
                            to={`/projects/${projectId}/bom/${line.id}/search`}
                            className="inline-flex items-center rounded-md bg-blue-600 px-2 py-0.5 text-[11px] font-medium text-white hover:bg-blue-700"
                            title="Manual search for part"
                          >
                            Search
                          </Link>
                        </span>
                      )}
                    </td>
                  )}
                  {show('manufacturer') && (
                    <td className="px-4 py-2.5 text-xs text-gray-700 dark:text-gray-300">
                      {result?.manufacturer ?? <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('source') && (
                    <td className="px-4 py-2.5">
                      {line.matched_provider ? (
                        <span className="inline-block rounded px-1.5 py-0.5 text-xs font-medium bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-400">
                          {line.matched_provider}
                        </span>
                      ) : (
                        <span className="text-gray-300 text-xs dark:text-gray-600">—</span>
                      )}
                    </td>
                  )}
                  {show('stock') && (
                    <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700 dark:text-gray-300">
                      {result != null
                        ? result.stock.toLocaleString()
                        : <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('price') && (
                    <td className="px-4 py-2.5 text-right tabular-nums text-xs text-gray-700 dark:text-gray-300">
                      {result?.unit_price != null
                        ? result.unit_price.toFixed(4)
                        : <span className="text-gray-400 dark:text-gray-500">—</span>}
                    </td>
                  )}
                  {show('status') && (
                    <td className="px-4 py-2.5">
                      <ConfidenceIndicator matchType={line.match_type} />
                    </td>
                  )}
                  {show('alerts') && (
                    <td className="px-4 py-2.5">
                      {flag ? (
                        <button
                          onClick={() => ackMutation.mutate(flag.id)}
                          disabled={ackMutation.isPending && ackMutation.variables === flag.id}
                          title={`${flag.flag_type === 'out_of_stock' ? 'Out of stock' : 'Price changed'} — click to acknowledge`}
                          className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 hover:bg-amber-100 disabled:opacity-50"
                        >
                          ⚠ {flag.flag_type === 'out_of_stock' ? 'OOS' : 'Price'}
                        </button>
                      ) : (
                        <span className="text-gray-300">—</span>
                      )}
                    </td>
                  )}
                  {show('notes') && (
                    <td className="px-4 py-2.5 text-xs text-gray-600 max-w-[12rem] dark:text-gray-400">
                      <EditableCell
                        value={line.notes}
                        multiline
                        placeholder="Add note…"
                        onSave={(v) => handlePatch(line.id, { notes: v || null })}
                      />
                    </td>
                  )}
                  {show('lifecycle') && (
                    <td className="px-4 py-2.5 text-xs text-gray-400 dark:text-gray-500">
                      {result?.lifecycle_status ?? '—'}
                    </td>
                  )}
                  {show('datasheet') && (
                    <td className="px-4 py-2.5 text-xs">
                      {datasheetUrl ? (
                        <a
                          href={datasheetUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          View
                        </a>
                      ) : (
                        <EditableCell
                          value={line.datasheet_url}
                          type="url"
                          placeholder="https://…"
                          onSave={(v) => handlePatch(line.id, { datasheet_url: v || null })}
                        />
                      )}
                    </td>
                  )}

                  {/* Lock / unlock */}
                  <td className="px-3 py-2.5">
                    <button
                      onClick={() =>
                        lockMutation.mutate({ lineId: line.id, locked: !line.locked })
                      }
                      disabled={
                        lockMutation.isPending &&
                        (lockMutation.variables as { lineId: number })?.lineId === line.id
                      }
                      title={line.locked ? 'Unlock this part' : 'Lock this part'}
                      className="text-lg leading-none transition hover:scale-110 disabled:opacity-50"
                    >
                      {line.locked ? '🔒' : '🔓'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>

          {/* UIF-011 / UIF-016: Summary row — one td per visible column */}
          <tfoot>
            <tr className="border-t-2 border-gray-200 bg-gray-50 text-xs font-medium text-gray-700 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-300">
              <td className="px-4 py-2.5 text-gray-400 dark:text-gray-500">Total</td>
              {show('thumbnail') && <td />}
              {show('ref') && <td />}
              {show('value') && <td />}
              {show('footprint') && <td />}
              {show('mpn_raw') && <td />}
              {show('qty') && (
                <td className="px-4 py-2.5 text-right tabular-nums">{totalQty}</td>
              )}
              {show('matched_mpn') && <td />}
              {show('manufacturer') && <td />}
              {show('source') && <td />}
              {show('stock') && <td />}
              {show('price') && (
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {hasAnyPrice ? (
                    <span>
                      {totalPrice.toFixed(2)}{' '}
                      <span className="text-gray-400">{currency}</span>
                    </span>
                  ) : (
                    <span className="text-gray-400">—</span>
                  )}
                </td>
              )}
              {show('status') && <td />}
              {show('alerts') && <td />}
              {show('notes') && <td />}
              {show('lifecycle') && <td />}
              {show('datasheet') && <td />}
              <td /> {/* lock column */}
            </tr>
          </tfoot>
        </table>

        <div className="border-t border-gray-200 px-4 py-2 text-xs text-gray-400 dark:border-gray-700 dark:text-gray-500">
          {lines.length} {lines.length === 1 ? 'line' : 'lines'}
        </div>
      </div>

      {/* Split row confirmation dialog */}
      {splitConfirmLine !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl dark:bg-gray-800">
            <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">Split Row</h3>
            <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
              This will split the row into individual lines. <span className="font-medium text-red-600 dark:text-red-400">This action cannot be undone.</span>
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setSplitConfirmLine(null)}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600"
              >
                Cancel
              </button>
              <button
                onClick={() => splitMutation.mutate(splitConfirmLine)}
                disabled={splitMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {splitMutation.isPending ? 'Splitting…' : 'OK'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
