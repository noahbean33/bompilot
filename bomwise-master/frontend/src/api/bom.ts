import type { AiAdvisorResult, BomImportResponse, BomLine, ManualSearchResponse, MatchResponse, PartAlternative, PartResult, SubstitutionHistoryEntry, SwapResponse } from '../types'
import api from './client'

export async function fetchBomLines(projectId: number): Promise<BomLine[]> {
  const { data } = await api.get<BomLine[]>(`/projects/${projectId}/bom`)
  return data
}

export async function getBomLine(projectId: number, lineId: number): Promise<BomLine> {
  const { data } = await api.get<BomLine>(`/projects/${projectId}/bom/${lineId}`)
  return data
}

export async function importBom(
  projectId: number,
  file: File,
): Promise<BomImportResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<BomImportResponse>(
    `/projects/${projectId}/bom/import`,
    form,
  )
  return data
}

export async function fetchPartResults(
  projectId: number,
  lineId: number,
): Promise<PartResult[]> {
  const { data } = await api.get<PartResult[]>(
    `/projects/${projectId}/bom/${lineId}/results`,
  )
  return data
}

export async function selectPartResult(
  projectId: number,
  lineId: number,
  selectedResultId: number,
): Promise<BomLine> {
  const { data } = await api.put<BomLine>(
    `/projects/${projectId}/bom/${lineId}`,
    { selected_result_id: selectedResultId },
  )
  return data
}

export interface BomLinePatch {
  quantity?: number | null
  reference?: string | null
  datasheet_url?: string | null
  notes?: string | null
  selected_result_id?: number | null
}

export async function patchBomLine(
  projectId: number,
  lineId: number,
  patch: BomLinePatch,
): Promise<BomLine> {
  const { data } = await api.patch<BomLine>(
    `/projects/${projectId}/bom/${lineId}`,
    patch,
  )
  return data
}

export async function matchProject(projectId: number): Promise<MatchResponse> {
  const { data } = await api.post<MatchResponse>(`/projects/${projectId}/match`)
  return data
}

export async function fetchSubstitutionHistory(
  projectId: number,
  lineId: number,
): Promise<SubstitutionHistoryEntry[]> {
  const { data } = await api.get<SubstitutionHistoryEntry[]>(
    `/projects/${projectId}/bom/${lineId}/history`,
  )
  return data
}

export async function fetchAlternatives(
  projectId: number,
  lineId: number,
): Promise<PartAlternative[]> {
  const { data } = await api.get<PartAlternative[]>(
    `/projects/${projectId}/bom/${lineId}/alternatives`,
  )
  return data
}

export async function lockBomLine(projectId: number, lineId: number): Promise<BomLine> {
  const { data } = await api.post<BomLine>(`/projects/${projectId}/bom/${lineId}/lock`)
  return data
}

export async function unlockBomLine(projectId: number, lineId: number): Promise<BomLine> {
  const { data } = await api.post<BomLine>(`/projects/${projectId}/bom/${lineId}/unlock`)
  return data
}

export async function lockAllBomLines(projectId: number, lineIds?: number[]): Promise<{ locked_count: number }> {
  const { data } = await api.post<{ locked_count: number }>(
    `/projects/${projectId}/bom/lock-all`,
    lineIds ? { line_ids: lineIds } : {},
  )
  return data
}

export async function unlockAllBomLines(projectId: number, lineIds?: number[]): Promise<{ unlocked_count: number }> {
  const { data } = await api.post<{ unlocked_count: number }>(
    `/projects/${projectId}/bom/unlock-all`,
    lineIds ? { line_ids: lineIds } : {},
  )
  return data
}

export async function downloadManufacturerBom(
  projectId: number,
  format: 'csv' | 'xlsx',
): Promise<void> {
  const resp = await api.get(`/projects/${projectId}/export/manufacturer`, {
    params: { format },
    responseType: 'blob',
  })
  const cd: string = resp.headers['content-disposition'] ?? ''
  const match = cd.match(/filename="([^"]+)"/)
  const filename = match ? match[1] : `manufacturer_bom.${format}`
  const url = URL.createObjectURL(new Blob([resp.data]))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// NL query
// ---------------------------------------------------------------------------

export interface NlFilter {
  field: string
  op: string
  value: string | number | boolean | null
}

export interface NlPreset {
  label: string
  filters: NlFilter[]
  highlightOnly?: boolean
}

export const NL_PRESETS: NlPreset[] = [
  { label: 'No Match',      filters: [{ field: 'match_type', op: 'eq', value: 'no_match' }] },
  { label: 'Exact MPN',     filters: [{ field: 'match_type', op: 'eq', value: 'exact_mpn' }] },
  { label: 'Keyword Match', filters: [{ field: 'match_type', op: 'eq', value: 'keyword' }] },
  { label: 'Unmatched',     filters: [{ field: 'matched_mpn', op: 'is_null', value: null }] },
  { label: 'Resistors',     filters: [{ field: 'category', op: 'eq', value: 'resistor' }] },
  { label: 'Capacitors',    filters: [{ field: 'category', op: 'eq', value: 'capacitor' }] },
  { label: 'Stock < 100',   filters: [{ field: 'stock', op: 'lt', value: 100 }] },
  { label: 'Locked',        filters: [{ field: 'locked', op: 'eq', value: true }] },
  // Highlight-only presets (visual only, no filtering)
  { label: '★ Highlight Resistors',  filters: [{ field: 'category', op: 'eq', value: 'resistor' }], highlightOnly: true },
  { label: '★ Highlight Capacitors', filters: [{ field: 'category', op: 'eq', value: 'capacitor' }], highlightOnly: true },
  { label: '★ Highlight ICs',        filters: [{ field: 'category', op: 'eq', value: 'ic' }], highlightOnly: true },
  { label: '★ Highlight No Match',   filters: [{ field: 'match_type', op: 'eq', value: 'no_match' }], highlightOnly: true },
]

/** Merge built-in user NL presets. Built-in first, custom after (prefixed). */
export function mergeNLPresets(
  builtIn: NlPreset[],
  custom: NlPreset[] = [],
): NlPreset[] {
  const customLabels = new Set(custom.map((p) => p.label))
  const builtInFiltered = builtIn.filter((p) => !customLabels.has(p.label))
  return [
    ...builtInFiltered,
    ...custom.map((p) => ({ ...p, label: `⚡ ${p.label}` })),
  ]
}

export interface NlQueryResult {
  filters: NlFilter[]
  highlight_only: boolean
  explanation: string
}

export async function runNlQuery(
  projectId: number,
  query: string,
): Promise<NlQueryResult> {
  const { data } = await api.post<NlQueryResult>(
    `/projects/${projectId}/bom/nl-query`,
    { query },
  )
  return data
}

// ---------------------------------------------------------------------------
// AI Assist
// ---------------------------------------------------------------------------

export interface BomLineSplitResponse {
  original_id: number
  new_line_ids: number[]
  total_lines: number
}

export async function splitBomLine(
  projectId: number,
  lineId: number,
): Promise<BomLineSplitResponse> {
  const { data } = await api.post<BomLineSplitResponse>(
    `/projects/${projectId}/bom/${lineId}/split`,
  )
  return data
}

export interface AiAssistBudget {
  used: number
  limit: number | null
  remaining: number | null
  resets_at: string
  unlimited: boolean
}

export interface AiAssistResult {
  processed: number
  skipped_budget: number
  no_part_needed: number
  ai_suggested: number
  no_match: number
  budget: AiAssistBudget
}

export async function fetchAiAssistBudget(projectId: number): Promise<AiAssistBudget> {
  const { data } = await api.get<AiAssistBudget>(`/projects/${projectId}/ai-assist/budget`)
  return data
}

export async function runAiAssist(projectId: number): Promise<AiAssistResult> {
  const { data } = await api.post<AiAssistResult>(`/projects/${projectId}/ai-assist`)
  return data
}

export async function swapPart(
  projectId: number,
  lineId: number,
  mpn: string,
  manufacturer?: string | null,
): Promise<SwapResponse> {
  const { data } = await api.post<SwapResponse>(
    `/projects/${projectId}/bom/${lineId}/swap`,
    { mpn, manufacturer: manufacturer ?? null },
  )
  return data
}

// ---------------------------------------------------------------------------
// Manual Search
// ---------------------------------------------------------------------------

export async function manualSearch(
  projectId: number,
  lineId: number,
  query: string,
  provider: string | null = null,
): Promise<ManualSearchResponse> {
  const { data } = await api.post<ManualSearchResponse>(
    `/projects/${projectId}/bom/${lineId}/manual-search`,
    { query, provider },
  )
  return data
}

// ---------------------------------------------------------------------------
// AI Advisor
// ---------------------------------------------------------------------------

export async function runAiAdvisor(
  projectId: number,
  lineId: number,
  selectedMpns: string[],
): Promise<AiAdvisorResult> {
  const { data } = await api.post<AiAdvisorResult>(
    `/projects/${projectId}/bom/${lineId}/ai-advisor`,
    { selected_mpns: selectedMpns },
  )
  return data
}

