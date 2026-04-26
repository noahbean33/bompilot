import type { PartFlag } from '../types'
import api from './client'

export async function fetchProjectFlags(projectId: number): Promise<PartFlag[]> {
  const { data } = await api.get<PartFlag[]>(`/projects/${projectId}/flags`)
  return data
}

export async function acknowledgeFlag(flagId: number): Promise<PartFlag> {
  const { data } = await api.post<PartFlag>(`/flags/${flagId}/acknowledge`)
  return data
}
