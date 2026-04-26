import api from './client'

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

export async function fetchUserUsage(period: string = 'week'): Promise<UserUsageSummary> {
  const { data } = await api.get<UserUsageSummary>('/users/me/usage', { params: { period } })
  return data
}