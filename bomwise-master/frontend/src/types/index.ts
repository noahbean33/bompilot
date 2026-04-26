export interface User {
  id: number
  email: string
  name: string | null
  subscription_tier: string
  is_active: boolean
  is_admin: boolean
  created_at: string
  email_verified_at: string | null
  last_login_at: string | null
  trial_ends_at: string | null
}

export interface Project {
  id: number
  user_id: number
  name: string
  description: string | null
  variant_tag: string | null
  created_at: string
  updated_at: string | null
}

export interface PartResult {
  id: number
  rank: number
  mpn: string
  manufacturer: string
  description: string | null
  package: string | null
  distributor: string | null
  unit_price: number | null
  stock: number
  lifecycle_status: string | null
  tech_specs: Record<string, string> | null
  datasheet_url: string | null
  image_url: string | null
  source_provider: string
  match_type: string
  retrieved_at: string
}

export interface BomLine {
  id: number
  project_id: number
  reference: string | null
  value: string | null
  footprint: string | null
  description: string | null
  quantity: number | null
  mpn_raw: string | null
  raw_fields: Record<string, string>
  match_type: string | null
  pinned: boolean
  locked: boolean
  notes: string | null
  datasheet_url: string | null
  matched_provider: string | null
  dnp: boolean
  created_at: string
  selected_result: PartResult | null
}

export interface MatchResponse {
  project_id: number
  total: number
  matched: number
  unmatched: number
}

export interface ProviderCapabilities {
  has_lifecycle_status: boolean
  has_tech_specs: boolean
  has_datasheet_urls: boolean
  has_similar_parts: boolean
  has_parametric_search: boolean
  distributor_coverage: string[]
}

export interface Token {
  access_token: string
  token_type: string
}

export interface BomImportResponse {
  project_id: number
  imported: number
  warnings: string[]
}

export interface CreateProjectBody {
  name: string
  description?: string
  variant_tag?: string
}

export interface NlPresetFilter {
  field: string
  op: string
  value: string | number | boolean | null
}

export interface NlPreset {
  label: string
  filters: NlPresetFilter[]
  highlightOnly?: boolean
}

export interface UserPreferences {
  id: number
  user_id: number
  preferred_currency: string
  preferred_distributors: string[]
  preferred_nl_presets: NlPreset[]
  auto_lock_parts: boolean
  created_at: string
  updated_at: string | null
}

export interface ProjectPreferences {
  id: number
  project_id: number
  preferred_currency: string | null
  preferred_distributors: string[] | null
  created_at: string
  updated_at: string | null
}

export interface PartFlag {
  id: number
  part_result_id: number
  flag_type: string
  old_value: string | null
  new_value: string | null
  acknowledged: boolean
  created_at: string
}

export interface SubstitutionHistoryEntry {
  id: number
  bom_line_id: number
  from_mpn: string | null
  to_mpn: string
  swapped_at: string
  swapped_by: number | null
}

export interface PartAlternative {
  id: number
  bom_line_id: number
  mpn: string
  manufacturer: string | null
  description: string | null
  package: string | null
  distributor: string | null
  stock: number | null
  datasheet_url: string | null
  source: string
  match_score: number | null
  created_at: string
}

export interface SwapResponse extends BomLine {
  provider_error: boolean
}

export interface SubscriptionInfo {
  subscription_tier: string
  subscription_status: string | null
  subscription_plan: string | null
  subscription_current_period_end: string | null
  paddle_customer_id: string | null
  paddle_subscription_id: string | null
  is_trial_provisioned: boolean
  trial_ends_at: string | null
}

export interface CheckoutResponse {
  transaction_id: string
}

export interface SubscriptionActionResponse {
  subscription_status: string | null
  subscription_plan: string | null
  subscription_current_period_end: string | null
}

export interface ManualSearchResponse {
  results: PartResult[]
  provider_error: boolean
}

export interface AiAdvisorBudget {
  used: number
  limit: number | null
  remaining: number | null
  resets_at: string
  unlimited: boolean
}

export interface AiAdvisorResult {
  explanation: string
  recommendation: string
  reasoning: string
  cached: boolean
  budget: AiAdvisorBudget
  quota_exceeded: boolean
  mpns: string[]
}

export interface UserUsageSummary {
  period: string
  start_date: string
  end_date: string
  projects_count: number
  bom_lines_total: number
  matched_lines: number
  ai_assist_lines_db: number
  ai_assist_lines_monthly: number
  ai_advisor_queries_monthly: number
  time_saved_minutes: number
  time_saved_note: string
}

