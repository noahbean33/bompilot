import type { Token, User } from '../types'
import api from './client'

export async function register(email: string, name: string): Promise<void> {
  await api.post('/auth/register', { email, name })
}

export async function login(email: string, password: string): Promise<Token> {
  const { data } = await api.post<Token>('/auth/login', { email, password })
  return data
}

export async function refresh(): Promise<Token> {
  const { data } = await api.post<Token>('/auth/refresh')
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}

export async function me(): Promise<User> {
  const { data } = await api.get<User>('/auth/me')
  return data
}

export async function forgotPassword(email: string): Promise<void> {
  await api.post('/auth/forgot-password', { email })
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  await api.post('/auth/reset-password', { token, new_password: newPassword })
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  await api.post('/auth/change-password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
}
