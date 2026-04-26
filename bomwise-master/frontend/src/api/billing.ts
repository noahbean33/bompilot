import type { CheckoutResponse, SubscriptionActionResponse, SubscriptionInfo } from '../types'
import api from './client'

export async function fetchSubscription(): Promise<SubscriptionInfo> {
  const { data } = await api.get<SubscriptionInfo>('/billing/subscription')
  return data
}

export async function createCheckout(): Promise<CheckoutResponse> {
  const { data } = await api.post<CheckoutResponse>('/billing/subscribe')
  return data
}

export async function cancelSubscription(): Promise<SubscriptionActionResponse> {
  const { data } = await api.post<SubscriptionActionResponse>('/billing/cancel')
  return data
}

export async function reactivateSubscription(): Promise<SubscriptionActionResponse> {
  const { data } = await api.post<SubscriptionActionResponse>('/billing/reactivate')
  return data
}
