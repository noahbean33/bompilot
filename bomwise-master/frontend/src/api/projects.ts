import type { CreateProjectBody, Project } from '../types'
import api from './client'

export async function fetchProjects(): Promise<Project[]> {
  const { data } = await api.get<Project[]>('/projects/')
  return data
}

export async function fetchProject(id: number): Promise<Project> {
  const { data } = await api.get<Project>(`/projects/${id}`)
  return data
}

export async function createProject(body: CreateProjectBody): Promise<Project> {
  const { data } = await api.post<Project>('/projects/', body)
  return data
}

export async function deleteProject(id: number): Promise<void> {
  await api.delete(`/projects/${id}`)
}

export async function cloneProject(id: number): Promise<Project> {
  const { data } = await api.post<Project>(`/projects/${id}/clone`)
  return data
}
