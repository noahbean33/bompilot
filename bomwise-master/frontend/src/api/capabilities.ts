import type { ProviderCapabilities } from '../types'
import api from './client'

export async function fetchCapabilities(): Promise<ProviderCapabilities> {
  const { data } = await api.get<ProviderCapabilities>('/providers/capabilities')
  return data
}
