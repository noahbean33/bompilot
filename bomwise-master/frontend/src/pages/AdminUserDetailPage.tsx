import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  fetchUser,
  fetchPlatformSettings,
  disableUser,
  enableUser,
  resetUserPassword,
  updateUserLimits,
  makeUserAdmin,
  revokeUserAdmin,
  type AdminProjectSummary,
  type AdminUserDetail,
} from '../api/admin'

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
  confirmLabel = 'Confirm',
  danger = false,
}: {
  message: string
  onConfirm: () => void
  onCancel: () => void
  confirmLabel?: string
  danger?: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl dark:bg-gray-800">
        <p className="text-sm text-gray-700 dark:text-gray-300">{message}</p>
        <div className="mt-5 flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className={`rounded-lg px-4 py-2 text-sm font-medium text-white ${
              danger ? 'bg-red-600 hover:bg-red-700' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}

function ProjectsTable({ projects }: { projects: AdminProjectSummary[] }) {
  if (projects.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500">No projects yet.</p>
  }

  const totalBomLines = projects.reduce((s, p) => s + p.bom_line_count, 0)
  const totalAiLines = projects.reduce((s, p) => s + p.ai_assist_line_count, 0)

  return (
    <table className="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
      <thead className="bg-gray-50 dark:bg-gray-900/50">
        <tr>
          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Name</th>
          <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">BOM lines</th>
          <th className="px-3 py-2 text-right text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400" title="Lines with match_type ai_suggested or no_part_needed">AI-assisted</th>
          <th className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">Created</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
        {projects.map((p) => (
          <tr key={p.id}>
            <td className="px-3 py-2 text-gray-900 dark:text-gray-100">{p.name}</td>
            <td className="px-3 py-2 text-right tabular-nums text-gray-700 dark:text-gray-300">{p.bom_line_count}</td>
            <td className="px-3 py-2 text-right tabular-nums">
              {p.ai_assist_line_count > 0 ? (
                <span className="font-medium text-amber-700 dark:text-amber-400">{p.ai_assist_line_count}</span>
              ) : (
                <span className="text-gray-400 dark:text-gray-500">0</span>
              )}
            </td>
            <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{formatDate(p.created_at)}</td>
          </tr>
        ))}
      </tbody>
      <tfoot className="border-t-2 border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/50">
        <tr>
          <td className="px-3 py-2 text-xs font-semibold text-gray-500 dark:text-gray-400">
            {projects.length} project{projects.length !== 1 ? 's' : ''}
          </td>
          <td className="px-3 py-2 text-right tabular-nums text-xs font-semibold text-gray-700 dark:text-gray-300">{totalBomLines}</td>
          <td className="px-3 py-2 text-right tabular-nums text-xs font-semibold text-amber-700 dark:text-amber-400">{totalAiLines}</td>
          <td />
        </tr>
      </tfoot>
    </table>
  )
}

// ---------------------------------------------------------------------------
// Limits panel
// ---------------------------------------------------------------------------

function LimitsPanel({ user }: { user: AdminUserDetail }) {
  const queryClient = useQueryClient()

  const [plan, setPlan] = useState<'free' | 'paid'>(user.plan as 'free' | 'paid')
  const [maxProjects, setMaxProjects] = useState(
    user.max_projects_override !== null ? String(user.max_projects_override) : ''
  )
  const [maxParts, setMaxParts] = useState(
    user.max_parts_per_project_override !== null
      ? String(user.max_parts_per_project_override)
      : ''
  )
  const [aiAssistOverride, setAiAssistOverride] = useState(
    user.ai_assist_monthly_lines_override !== null
      ? String(user.ai_assist_monthly_lines_override)
      : ''
  )
  const [saved, setSaved] = useState(false)

  // Keep form in sync if parent data refreshes
  useEffect(() => {
    setPlan(user.plan as 'free' | 'paid')
    setMaxProjects(user.max_projects_override !== null ? String(user.max_projects_override) : '')
    setMaxParts(
      user.max_parts_per_project_override !== null
        ? String(user.max_parts_per_project_override)
        : ''
    )
    setAiAssistOverride(
      user.ai_assist_monthly_lines_override !== null
        ? String(user.ai_assist_monthly_lines_override)
        : ''
    )
  }, [user.plan, user.max_projects_override, user.max_parts_per_project_override, user.ai_assist_monthly_lines_override])

  const { data: globals } = useQuery({
    queryKey: ['platformSettings'],
    queryFn: fetchPlatformSettings,
  })

  const mutation = useMutation({
    mutationFn: () =>
      updateUserLimits(user.id, {
        plan,
        max_projects_override: maxProjects !== '' ? Number(maxProjects) : null,
        max_parts_per_project_override: maxParts !== '' ? Number(maxParts) : null,
        ai_assist_monthly_lines_override: aiAssistOverride !== '' ? Number(aiAssistOverride) : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.id] })
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
  })

  const defaultMaxProjects = globals?.free_plan_max_projects ?? '…'
  const defaultMaxParts = globals?.free_plan_max_parts_per_project ?? '…'
  const defaultAiFree = globals?.ai_assist_free_monthly_lines ?? '…'
  const defaultAiPaid = globals?.ai_assist_paid_monthly_lines ?? '…'
  const defaultAi = plan === 'paid' ? defaultAiPaid : defaultAiFree

  const inputCls = 'w-full rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 dark:disabled:bg-gray-800 dark:disabled:text-gray-500'

  return (
    <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
      <h2 className="mb-4 text-sm font-semibold text-gray-700 dark:text-gray-300">Plan &amp; Limits</h2>

      <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {/* Plan */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 dark:text-gray-400">Plan</label>
          <select
            value={plan}
            onChange={(e) => setPlan(e.target.value as 'free' | 'paid')}
            className={inputCls}
          >
            <option value="free">Free</option>
            <option value="paid">Paid</option>
          </select>
        </div>

        {/* Max projects override */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 dark:text-gray-400">
            Max projects override
          </label>
          <input
            type="number"
            min={1}
            value={maxProjects}
            onChange={(e) => setMaxProjects(e.target.value)}
            placeholder={`Default: ${defaultMaxProjects}`}
            disabled={plan === 'paid'}
            className={inputCls}
          />
          <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">Leave blank to use global default</p>
        </div>

        {/* Max parts override */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 dark:text-gray-400">
            Max parts per project override
          </label>
          <input
            type="number"
            min={1}
            value={maxParts}
            onChange={(e) => setMaxParts(e.target.value)}
            placeholder={`Default: ${defaultMaxParts}`}
            disabled={plan === 'paid'}
            className={inputCls}
          />
          <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">Leave blank to use global default</p>
        </div>

        {/* AI Assist override */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1 dark:text-gray-400">
            AI Assist lines/month override
          </label>
          <input
            type="number"
            min={0}
            value={aiAssistOverride}
            onChange={(e) => setAiAssistOverride(e.target.value)}
            placeholder={`Default: ${defaultAi}`}
            className={inputCls}
          />
          <p className="mt-0.5 text-xs text-gray-400 dark:text-gray-500">0 = unlimited. Blank = global default</p>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-3">
        <button
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
        >
          {mutation.isPending ? 'Saving…' : 'Save limits'}
        </button>
        {saved && <span className="text-xs text-green-600 dark:text-green-400">Saved</span>}
        {mutation.isError && (
          <span className="text-xs text-red-600 dark:text-red-400">Save failed</span>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function AdminUserDetailPage() {
  const { userId } = useParams<{ userId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const id = Number(userId)

  const [dialog, setDialog] = useState<null | 'disable' | 'enable' | 'reset' | 'make-admin' | 'revoke-admin'>(null)

  const { data: user, isLoading, isError } = useQuery({
    queryKey: ['adminUser', id],
    queryFn: () => fetchUser(id),
    enabled: !isNaN(id),
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['adminUser', id] })
    queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
  }

  const disableMutation = useMutation({
    mutationFn: () => disableUser(id),
    onSuccess: invalidate,
  })

  const enableMutation = useMutation({
    mutationFn: () => enableUser(id),
    onSuccess: invalidate,
  })

  const resetMutation = useMutation({
    mutationFn: () => resetUserPassword(id),
    onSuccess: () => setDialog(null),
  })

  const makeAdminMutation = useMutation({
    mutationFn: () => makeUserAdmin(id),
    onSuccess: () => { invalidate(); setDialog(null) },
  })

  const revokeAdminMutation = useMutation({
    mutationFn: () => revokeUserAdmin(id),
    onSuccess: () => { invalidate(); setDialog(null) },
  })

  const isBusy = disableMutation.isPending || enableMutation.isPending || resetMutation.isPending || makeAdminMutation.isPending || revokeAdminMutation.isPending

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (isError || !user) {
    return (
      <div className="rounded-lg bg-red-50 p-4 text-sm text-red-700 dark:bg-red-900/20 dark:text-red-400">
        Failed to load user.
      </div>
    )
  }

  return (
    <>
      {/* Confirm dialogs */}
      {dialog === 'disable' && (
        <ConfirmDialog
          message={`Disable account for ${user.email}? They will no longer be able to log in.`}
          confirmLabel="Disable account"
          danger
          onConfirm={() => { setDialog(null); disableMutation.mutate() }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'enable' && (
        <ConfirmDialog
          message={`Re-enable account for ${user.email}?`}
          confirmLabel="Enable account"
          onConfirm={() => { setDialog(null); enableMutation.mutate() }}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'reset' && (
        <ConfirmDialog
          message={`Send a password reset email to ${user.email}?`}
          confirmLabel="Send email"
          onConfirm={() => resetMutation.mutate()}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'make-admin' && (
        <ConfirmDialog
          message={`Grant admin privileges to ${user.email}?`}
          confirmLabel="Make admin"
          onConfirm={() => makeAdminMutation.mutate()}
          onCancel={() => setDialog(null)}
        />
      )}
      {dialog === 'revoke-admin' && (
        <ConfirmDialog
          message={`Revoke admin privileges from ${user.email}?`}
          confirmLabel="Revoke admin"
          danger
          onConfirm={() => revokeAdminMutation.mutate()}
          onCancel={() => setDialog(null)}
        />
      )}

      {/* Back link */}
      <button
        onClick={() => navigate('/admin/users')}
        className="mb-4 text-sm text-blue-600 hover:underline dark:text-blue-400"
      >
        ← Back to users
      </button>

      <div className="space-y-6">
        {/* Header card */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">{user.email}</h1>
              {user.name && <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">{user.name}</p>}
              <div className="mt-2 flex flex-wrap gap-2">
                <span
                  className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                    user.is_active
                      ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
                      : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
                  }`}
                >
                  {user.is_active ? 'active' : 'disabled'}
                </span>
          {user.is_admin && (
            <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
              admin
            </span>
          )}
          {user.trial_status === 'active-trial' && (
            <span className="inline-block rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-400">
              active-trial
            </span>
          )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-2">
              {user.is_active ? (
                <button
                  onClick={() => setDialog('disable')}
                  disabled={isBusy}
                  className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20"
                >
                  Disable account
                </button>
              ) : (
                <button
                  onClick={() => setDialog('enable')}
                  disabled={isBusy}
                  className="rounded-lg border border-green-300 px-3 py-1.5 text-xs font-medium text-green-700 hover:bg-green-50 disabled:opacity-50 dark:border-green-800 dark:text-green-400 dark:hover:bg-green-900/20"
                >
                  Enable account
                </button>
              )}
              {user.is_admin ? (
                <button
                  onClick={() => setDialog('revoke-admin')}
                  disabled={isBusy}
                  className="rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50 dark:border-amber-800 dark:text-amber-400 dark:hover:bg-amber-900/20"
                >
                  {revokeAdminMutation.isPending ? 'Revoking…' : 'Revoke admin'}
                </button>
              ) : (
                <button
                  onClick={() => setDialog('make-admin')}
                  disabled={isBusy}
                  className="rounded-lg border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50 disabled:opacity-50 dark:border-amber-800 dark:text-amber-400 dark:hover:bg-amber-900/20"
                >
                  {makeAdminMutation.isPending ? 'Granting…' : 'Make admin'}
                </button>
              )}
              <button
                onClick={() => setDialog('reset')}
                disabled={isBusy}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
              >
                {resetMutation.isPending ? 'Sending…' : 'Send password reset email'}
              </button>
            </div>
          </div>

          {/* Meta */}
          <dl className="mt-5 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
            {[
              { label: 'Joined', value: formatDate(user.created_at) },
              { label: 'Projects', value: user.projects_count },
              { label: 'BOM lines', value: user.bom_lines_total },
              { label: 'Matched lines', value: user.matched_lines_total },
            ].map(({ label, value }) => (
              <div key={label}>
                <dt className="text-xs text-gray-400 dark:text-gray-500">{label}</dt>
                <dd className="font-medium text-gray-700 dark:text-gray-300">{value}</dd>
              </div>
            ))}
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">AI-assisted (total)</dt>
              <dd className="font-medium text-amber-700 dark:text-amber-400">{user.ai_assist_lines_total}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">AI lines this month</dt>
              <dd className="font-medium text-amber-700 dark:text-amber-400">{user.ai_assist_lines_this_month}</dd>
            </div>
          </dl>

          {resetMutation.isSuccess && (
            <p className="mt-3 text-xs text-green-600 dark:text-green-400">Password reset email sent.</p>
          )}
        </div>

        {/* Plan & Limits */}
        <LimitsPanel user={user} />

        {/* Billing / Paddle */}
        <div className="rounded-xl bg-white p-6 shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
          <h2 className="mb-4 text-sm font-semibold text-gray-700 dark:text-gray-300">Billing (read-only)</h2>
          <dl className="grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
            {[
              { label: 'Subscription tier', value: user.subscription_tier },
              { label: 'Subscription status', value: user.subscription_status ?? '—' },
              { label: 'Subscription plan', value: user.subscription_plan ?? '—' },
              { label: 'Period ends', value: formatDate(user.subscription_current_period_end) },
            ].map(({ label, value }) => (
              <div key={label}>
                <dt className="text-xs text-gray-400 dark:text-gray-500">{label}</dt>
                <dd className="font-medium text-gray-700 dark:text-gray-300">{value}</dd>
              </div>
            ))}
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">Trial provisioned</dt>
              <dd className="font-medium text-gray-700 dark:text-gray-300">{user.is_trial_provisioned ? 'Yes' : 'No'}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">Trial expires</dt>
              <dd className="font-medium text-gray-700 dark:text-gray-300">{formatDate(user.trial_ends_at)}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">Paddle customer ID</dt>
              <dd className="font-mono text-xs text-gray-600 dark:text-gray-400">{user.paddle_customer_id ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-gray-400 dark:text-gray-500">Paddle subscription ID</dt>
              <dd className="font-mono text-xs text-gray-600 dark:text-gray-400">{user.paddle_subscription_id ?? '—'}</dd>
            </div>
          </dl>
        </div>

        {/* Projects table */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-gray-700 dark:text-gray-300">Projects</h2>
          <div className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-gray-200 dark:bg-gray-800 dark:ring-gray-700">
            <div className="p-4">
              <ProjectsTable projects={user.projects} />
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
