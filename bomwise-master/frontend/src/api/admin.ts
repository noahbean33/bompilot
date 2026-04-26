import api from './client'

export interface ProviderStatus {
  name: string
  enabled: boolean
  last_called_at: string | null
  last_success_at: string | null
  calls_today: number
  errors_today: number
  daily_limit: number | null
  limit_remaining: number | null
}

export interface PingResult {
  success: boolean
  latency_ms: number
  error: string | null
}

export async function fetchProviderStatus(): Promise<ProviderStatus[]> {
  const { data } = await api.get<ProviderStatus[]>('/admin/providers/status')
  return data
}

export async function pingProvider(name: string): Promise<PingResult> {
  const { data } = await api.post<PingResult>(`/admin/providers/${name}/ping`)
  return data
}

export interface ProviderErrorEntry {
  id: number
  error_type: string
  message: string
  status_code: number | null
  occurred_at: string
}

export interface ProviderErrorsResponse {
  provider_name: string
  errors: ProviderErrorEntry[]
  total_in_24h: number
}

export async function fetchProviderErrors(
  providerName: string,
  limit = 10,
): Promise<ProviderErrorsResponse> {
  const { data } = await api.get<ProviderErrorsResponse>(
    `/admin/providers/${providerName}/errors`,
    { params: { limit } },
  )
  return data
}

export async function clearProviderErrors(
  providerName: string,
): Promise<{ deleted: number }> {
  const { data } = await api.delete<{ deleted: number }>(
    `/admin/providers/${providerName}/errors`,
  )
  return data
}

export interface AdminStats {
  users_total: number
  users_active_30d: number
  pro_users_total: number
  free_users_total: number
  projects_total: number
  projects_per_user_avg: number
  bom_lines_total: number
  bom_lines_matched: number
  match_rate_pct: number
  providers_breakdown: Record<string, number>
}

export async function fetchAdminStats(): Promise<AdminStats> {
  const { data } = await api.get<AdminStats>('/admin/stats')
  return data
}

// ---------------------------------------------------------------------------
// AI usage
// ---------------------------------------------------------------------------

export interface AiUsageEntry {
  feature: string
  input_tokens: number
  output_tokens: number
  input_cost_usd: number
  output_cost_usd: number
  total_tokens: number
  total_cost_usd: number
}

export interface AiUsageDailyEntry {
  date: string
  feature: string
  input_tokens: number
  output_tokens: number
  input_cost_usd: number
  output_cost_usd: number
  total_tokens: number
  total_cost_usd: number
}

export interface AiUsageBreakdown {
  free_tokens: number
  pro_tokens: number
  free_cost_usd: number
  pro_cost_usd: number
  note: string
}

export interface AiUsageResponse {
  start_date: string
  end_date: string
  daily: AiUsageDailyEntry[]
  summary: AiUsageEntry[]
  breakdown: AiUsageBreakdown
  total_cost_usd: number
  rate_note: string
}

export async function fetchAiUsage(params?: {
  start_date?: string
  end_date?: string
}): Promise<AiUsageResponse> {
  const { data } = await api.get<AiUsageResponse>('/admin/ai/usage', { params })
  return data
}

// ---------------------------------------------------------------------------
// User management
// ---------------------------------------------------------------------------

export interface AdminUserSummary {
  id: number
  email: string
  name: string | null
  is_admin: boolean
  is_active: boolean
  plan: string
  subscription_tier: string
  max_projects_override: number | null
  max_parts_per_project_override: number | null
  ai_assist_monthly_lines_override: number | null
  created_at: string
  projects_count: number
  last_login_at: string | null
  ai_assist_lines_this_month: number
  paddle_customer_id: string | null
  paddle_subscription_id: string | null
  subscription_status: string | null
  subscription_plan: string | null
  subscription_current_period_end: string | null
  is_trial_provisioned: boolean
  trial_ends_at: string | null
  trial_status: string | null
}

export interface AdminProjectSummary {
  id: number
  name: string
  created_at: string | null
  bom_line_count: number
  ai_assist_line_count: number
}

export interface AdminUserDetail extends AdminUserSummary {
  bom_lines_total: number
  matched_lines_total: number
  ai_assist_lines_total: number
  projects: AdminProjectSummary[]
}

export interface AdminUserList {
  total: number
  page: number
  page_size: number
  items: AdminUserSummary[]
}

export async function fetchUsers(params: {
  page?: number
  page_size?: number
  search?: string
}): Promise<AdminUserList> {
  const { data } = await api.get<AdminUserList>('/admin/users', { params })
  return data
}

export async function fetchUser(userId: number): Promise<AdminUserDetail> {
  const { data } = await api.get<AdminUserDetail>(`/admin/users/${userId}`)
  return data
}

export async function disableUser(userId: number): Promise<void> {
  await api.post(`/admin/users/${userId}/disable`)
}

export async function enableUser(userId: number): Promise<void> {
  await api.post(`/admin/users/${userId}/enable`)
}

export async function resetUserPassword(userId: number): Promise<void> {
  await api.post(`/admin/users/${userId}/reset-password`)
}

export interface UserLimitsUpdate {
  plan: 'free' | 'paid'
  max_projects_override: number | null
  max_parts_per_project_override: number | null
  ai_assist_monthly_lines_override: number | null
}

export async function updateUserLimits(userId: number, body: UserLimitsUpdate): Promise<void> {
  await api.put(`/admin/users/${userId}/limits`, body)
}

export async function makeUserAdmin(userId: number): Promise<{ success: boolean; already_admin: boolean }> {
  const { data } = await api.post<{ success: boolean; already_admin: boolean }>(`/admin/users/${userId}/make-admin`)
  return data
}

export async function revokeUserAdmin(userId: number): Promise<{ success: boolean; already_not_admin: boolean }> {
  const { data } = await api.post<{ success: boolean; already_not_admin: boolean }>(`/admin/users/${userId}/revoke-admin`)
  return data
}

// ---------------------------------------------------------------------------
// Global platform settings
// ---------------------------------------------------------------------------

export interface PlatformSettings {
  free_plan_max_projects: number
  free_plan_max_parts_per_project: number
  provider_fallback_order: string
  // AI Assist budget (0 = unlimited)
  ai_assist_free_monthly_lines: number
  ai_assist_paid_monthly_lines: number
}

export async function fetchPlatformSettings(): Promise<PlatformSettings> {
  const { data } = await api.get<PlatformSettings>('/admin/settings')
  return data
}

export async function updatePlatformSettings(body: PlatformSettings): Promise<PlatformSettings> {
  const { data } = await api.put<PlatformSettings>('/admin/settings', body)
  return data
}
