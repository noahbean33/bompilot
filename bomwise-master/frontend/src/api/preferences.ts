import type { NlPreset, ProjectPreferences, UserPreferences } from '../types'
import api from './client'

// User preferences
export async function fetchUserPreferences(): Promise<UserPreferences> {
  const { data } = await api.get<UserPreferences>('/users/me/preferences')
  return data
}

export async function updateUserPreferences(body: {
  preferred_currency?: string | null
  preferred_distributors?: string[] | null
  preferred_nl_presets?: NlPreset[] | null
  auto_lock_parts?: boolean | null
}): Promise<UserPreferences> {
  const { data } = await api.put<UserPreferences>('/users/me/preferences', body)
  return data
}

// Project preferences
export async function fetchProjectPreferences(projectId: number): Promise<ProjectPreferences> {
  const { data } = await api.get<ProjectPreferences>(`/projects/${projectId}/preferences`)
  return data
}

export async function updateProjectPreferences(
  projectId: number,
  body: {
    preferred_currency?: string | null
    preferred_distributors?: string[] | null
  },
): Promise<ProjectPreferences> {
  const { data } = await api.put<ProjectPreferences>(
    `/projects/${projectId}/preferences`,
    body,
  )
  return data
}
