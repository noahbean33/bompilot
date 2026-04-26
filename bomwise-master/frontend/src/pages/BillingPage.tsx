import { useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchSubscription,
  createCheckout,
  cancelSubscription,
  reactivateSubscription,
} from '../api/billing'

// Paddle.js is loaded dynamically only when this component mounts.
declare global {
  interface Window {
    Paddle?: {
      Environment: { set: (env: string) => void }
      Initialize: (opts: {
        token: string
        eventCallback?: (event: { name: string; data?: Record<string, unknown> }) => void
      }) => void
      Checkout: {
        open: (opts: {
          transactionId?: string
          settings?: Record<string, unknown>
        }) => void
      }
    }
  }
}

const PADDLE_ENV = import.meta.env.VITE_PADDLE_ENVIRONMENT ?? 'sandbox'
const PADDLE_CLIENT_TOKEN = import.meta.env.VITE_PADDLE_CLIENT_TOKEN ?? ''

interface PaddleCallbacks {
  onCompleted: () => void
  onClosed: () => void
}

function usePaddleJs(callbacks: PaddleCallbacks) {
  const loaded = useRef(false)
  // Keep refs current so the Paddle event callback never closes over stale state
  const callbacksRef = useRef(callbacks)

  useEffect(() => {
    callbacksRef.current = callbacks
  })

  useEffect(() => {
    if (typeof window === 'undefined') return

    function initPaddle() {
      if (!window.Paddle) return
      window.Paddle.Environment.set(PADDLE_ENV)
      if (PADDLE_CLIENT_TOKEN) {
        window.Paddle.Initialize({
          token: PADDLE_CLIENT_TOKEN,
          eventCallback(event) {
            if (event.name === 'checkout.completed') {
              callbacksRef.current.onCompleted()
            } else if (event.name === 'checkout.closed') {
              callbacksRef.current.onClosed()
            }
          },
        })
      }
    }

    if (loaded.current) return
    const existing = document.querySelector('script[src*="paddle.js"]')
    if (existing) {
      initPaddle()
      loaded.current = true
      return
    }
    const script = document.createElement('script')
    script.src = 'https://cdn.paddle.com/paddle/v2/paddle.js'
    script.async = true
    script.onload = () => {
      initPaddle()
      loaded.current = true
    }
    document.head.appendChild(script)
  }, [])
}

function extractDetail(err: unknown): string {
  if (!err) return 'Something went wrong. Please try again.'
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? 'Something went wrong. Please try again.'
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  })
}

function StatusBadge({ status }: { status: string | null }) {
  if (!status) return null
  const styles: Record<string, string> = {
    active: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    past_due: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    cancelled: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    paused: 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400',
  }
  const label: Record<string, string> = {
    active: 'Active',
    past_due: 'Past Due',
    cancelled: 'Cancelled',
    paused: 'Paused',
  }
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${styles[status] ?? 'bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400'}`}
    >
      {label[status] ?? status}
    </span>
  )
}

export function BillingPage() {
  const queryClient = useQueryClient()
  const [showCancelDialog, setShowCancelDialog] = useState(false)
  const [checkoutLoading, setCheckoutLoading] = useState(false)
  const [optimisticProcessing, setOptimisticProcessing] = useState(false)

  usePaddleJs({
    onCompleted() {
      // Paddle fires checkout.completed when payment succeeds.
      setOptimisticProcessing(true)
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
      queryClient.invalidateQueries({ queryKey: ['currentUser'] })
    },
    onClosed() {
      // User closed the overlay without paying — clear any premature state.
      setOptimisticProcessing(false)
    },
  })

  const { data: sub, isLoading, isError } = useQuery({
    queryKey: ['subscription'],
    queryFn: fetchSubscription,
  })

  const cancelMutation = useMutation({
    mutationFn: cancelSubscription,
    onSuccess: () => {
      setShowCancelDialog(false)
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
      queryClient.invalidateQueries({ queryKey: ['currentUser'] })
    },
    onError: () => {
      setShowCancelDialog(false)
    },
  })

  const reactivateMutation = useMutation({
    mutationFn: reactivateSubscription,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['subscription'] })
      queryClient.invalidateQueries({ queryKey: ['currentUser'] })
    },
  })

  async function handleUpgrade() {
    setCheckoutLoading(true)
    try {
      const { transaction_id } = await createCheckout()
      if (window.Paddle) {
        // quantity widget is controlled by the Paddle price setting, not JS —
        // disable in Paddle Dashboard: Catalog → Prices → your price → uncheck
        // "Allow customers to change quantity"
        window.Paddle.Checkout.open({ transactionId: transaction_id })
      } else {
        // Fallback: open Paddle-hosted checkout if Paddle.js didn't load
        window.open(
          `https://checkout.paddle.com/checkout/custom/${transaction_id}`,
          '_blank',
          'noopener',
        )
      }
    } catch {
      alert('Failed to start checkout. Please try again.')
    } finally {
      setCheckoutLoading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (isError || !sub) {
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        Failed to load billing information.
      </div>
    )
  }

  const isTrialActive =
    sub.is_trial_provisioned &&
    sub.trial_ends_at &&
    new Date(sub.trial_ends_at) > new Date()
  const isPaddlePro = sub.subscription_tier === 'pro' && !!sub.paddle_subscription_id
  const isCancelled = sub.subscription_status === 'cancelled'
  const periodEnd = formatDate(sub.subscription_current_period_end)
  const trialEnd = formatDate(sub.trial_ends_at)

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Billing</h1>

      {/* Cancel confirmation dialog */}
      {showCancelDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl dark:bg-gray-800">
            <p className="text-sm text-gray-700 dark:text-gray-300">
              Your Pro access will continue until{' '}
              <strong>{periodEnd}</strong>. After that your account returns to
              Free.
            </p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setShowCancelDialog(false)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                Keep Pro
              </button>
              <button
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-60"
              >
                {cancelMutation.isPending ? 'Cancelling…' : 'Cancel subscription'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
        {isTrialActive ? (
          /* Trial provisioned — course bonus */
          <div className="space-y-5">
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Current plan</p>
              <p className="mt-0.5 text-xl font-semibold text-gray-900 dark:text-gray-100">Pro</p>
            </div>

            <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
              <p className="font-medium">Pro access active — course bonus</p>
              <p className="mt-1">Expires: <strong>{trialEnd}</strong></p>
              <p className="mt-2">Subscribe to continue Pro access after this date.</p>
            </div>

            <ul className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
              <li>Unlimited projects</li>
              <li>Unlimited parts per project</li>
              <li>500 AI-assisted lines per month</li>
            </ul>

            {optimisticProcessing && (
              <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
                Payment received — activating your Pro plan…
              </div>
            )}

            <button
              onClick={handleUpgrade}
              disabled={checkoutLoading || optimisticProcessing}
              className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {checkoutLoading ? 'Loading checkout…' : 'Subscribe to continue Pro — $10/month'}
            </button>
          </div>
        ) : !isPaddlePro ? (
          /* Free tier (or expired trial) — show current limits + upgrade benefits */
          <div className="space-y-5">
            <div>
              <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Current plan</p>
              <p className="mt-0.5 text-xl font-semibold text-gray-900 dark:text-gray-100">Free</p>
            </div>

            {/* Plan comparison table */}
            <div className="overflow-hidden rounded-lg border border-gray-200 text-sm dark:border-gray-700">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/50">
                    <th className="py-2 pl-4 text-left font-medium text-gray-600 dark:text-gray-400">Feature</th>
                    <th className="py-2 text-center font-medium text-gray-500 dark:text-gray-400">Free</th>
                    <th className="py-2 pr-4 text-center font-semibold text-blue-600 dark:text-blue-400">Pro</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                  {[
                    ['Projects', '3', 'Unlimited'],
                    ['Parts per project', '50', 'Unlimited'],
                    ['AI-assisted lines / month', '50', '500'],
                    ['Provider fallback chain', '✓', '✓'],
                    ['BOM CSV import', '✓', '✓'],
                    ['Part alternatives & variants', '✓', '✓'],
                  ].map(([feature, free, pro]) => (
                    <tr key={feature}>
                      <td className="py-2 pl-4 text-gray-700 dark:text-gray-300">{feature}</td>
                      <td className="py-2 text-center text-gray-500 dark:text-gray-400">{free}</td>
                      <td className="py-2 pr-4 text-center font-medium text-blue-700 dark:text-blue-400">{pro}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {optimisticProcessing && (
              <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-700 dark:bg-blue-900/20 dark:text-blue-300">
                Payment received — activating your Pro plan…
              </div>
            )}

            <button
              onClick={handleUpgrade}
              disabled={checkoutLoading || optimisticProcessing}
              className="w-full rounded-lg bg-blue-600 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
            >
              {checkoutLoading ? 'Loading checkout…' : 'Upgrade to Pro — $10/month'}
            </button>
          </div>
        ) : (
          /* Paddle Pro tier */
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-500 dark:text-gray-400">Current plan</p>
                <p className="mt-0.5 text-xl font-semibold text-gray-900 dark:text-gray-100">Pro</p>
              </div>
              <StatusBadge status={sub.subscription_status} />
            </div>

            {isCancelled ? (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Your Pro access continues until{' '}
                <strong>{periodEnd}</strong>. After that your account returns to Free.
              </p>
            ) : (
              <p className="text-sm text-gray-600 dark:text-gray-400">
                Renews{' '}
                <strong>{periodEnd}</strong>
              </p>
            )}

            <ul className="space-y-1 text-sm text-gray-600 dark:text-gray-400">
              <li>Unlimited projects</li>
              <li>Unlimited parts per project</li>
              <li>500 AI-assisted lines per month</li>
            </ul>

            {reactivateMutation.isSuccess && (
              <div className="rounded-lg bg-green-50 px-4 py-3 text-sm text-green-700 dark:bg-green-900/20 dark:text-green-400">
                Subscription reactivated.
              </div>
            )}

            {(cancelMutation.isError || reactivateMutation.isError) && (
              <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
                {extractDetail(cancelMutation.error ?? reactivateMutation.error)}
              </div>
            )}

            {isCancelled ? (
              <button
                onClick={() => reactivateMutation.mutate()}
                disabled={reactivateMutation.isPending}
                className="w-full rounded-lg bg-blue-600 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60"
              >
                {reactivateMutation.isPending ? 'Reactivating…' : 'Reactivate subscription'}
              </button>
            ) : (
              <button
                onClick={() => setShowCancelDialog(true)}
                className="w-full rounded-lg border border-red-300 py-2 text-sm font-medium text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20"
              >
                Cancel subscription
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
