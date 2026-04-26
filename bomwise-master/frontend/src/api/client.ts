import axios from 'axios'
import { useAuthStore } from '../store/authStore'

// Augment axios config to carry our retry flag
declare module 'axios' {
  interface InternalAxiosRequestConfig {
    _retry?: boolean
  }
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true, // send httpOnly refresh-token cookie on every request
})

// Attach the in-memory access token to every request
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Track a single in-flight refresh so concurrent 401s share one attempt
let refreshPromise: Promise<string> | null = null

api.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error)) return Promise.reject(error)

    const original = error.config
    const status = error.response?.status

    // Only retry once, and never retry the refresh call itself
    if (
      status === 401 &&
      original &&
      !original._retry &&
      !original.url?.includes('/auth/refresh')
    ) {
      original._retry = true
      try {
        if (!refreshPromise) {
          refreshPromise = api
            .post<{ access_token: string }>('/auth/refresh')
            .then((r) => {
              const newToken = r.data.access_token
              useAuthStore.getState().setToken(newToken)
              return newToken
            })
            .finally(() => {
              refreshPromise = null
            })
        }
        const newToken = await refreshPromise
        original.headers.Authorization = `Bearer ${newToken}`
        return api(original)
      } catch {
        useAuthStore.getState().logout()
        window.location.href = '/login'
      }
    }

    return Promise.reject(error)
  },
)

export default api

// Version endpoint — no auth required (uses raw fetch to avoid auth interceptor)
export async function getVersion(): Promise<{ version: string; commit: string; environment: string }> {
  const res = await fetch(`${BASE_URL}/version`)
  if (!res.ok) throw new Error('Failed to fetch version')
  return res.json()
}
