interface Config {
  dot: string
  label: string
  title: string
}

const MATCH_CONFIG: Record<string, Config> = {
  exact_mpn: {
    dot: 'bg-green-500',
    label: 'Exact MPN',
    title: 'Matched by exact manufacturer part number',
  },
  distributor_pn: {
    dot: 'bg-amber-400',
    label: 'Distributor PN',
    title: 'Matched by distributor part number',
  },
  parametric: {
    dot: 'bg-amber-400',
    label: 'Parametric',
    title: 'Matched by component specifications',
  },
  keyword: {
    dot: 'bg-red-500',
    label: 'Keyword',
    title: 'Matched by keyword search — low confidence',
  },
  no_part_needed: {
    dot: 'bg-gray-300',
    label: 'No part needed',
    title: 'Copper-only pad, test point, or fiducial — nothing to purchase',
  },
  ai_suggested: {
    dot: 'bg-amber-400',
    label: 'AI suggested',
    title: 'AI found candidates — review on the Alternatives page and select one',
  },
}

const PENDING: Config = {
  dot: 'bg-gray-300',
  label: 'Pending',
  title: 'Not yet matched',
}

const NO_MATCH: Config = {
  dot: 'bg-red-400',
  label: 'No match',
  title: 'No matching part found by the provider',
}

export function ConfidenceIndicator({ matchType }: { matchType: string | null }) {
  const cfg: Config =
    matchType === null
      ? PENDING
      : matchType === 'no_match'
        ? NO_MATCH
        : MATCH_CONFIG[matchType] ?? PENDING
  return (
    <span className="inline-flex items-center gap-1.5" title={cfg.title}>
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${cfg.dot}`} aria-hidden />
      <span className="text-xs text-gray-500 dark:text-gray-400">{cfg.label}</span>
    </span>
  )
}

/** Returns the Tailwind row background class for a given match_type. */
export function rowBgClass(matchType: string | null, locked: boolean, nlHighlighted: boolean): string {
  if (nlHighlighted) return 'ring-2 ring-purple-400 bg-purple-50 dark:bg-purple-900/20'
  if (locked) return 'bg-amber-50 dark:bg-amber-900/10'
  if (matchType === 'no_part_needed') return 'bg-gray-50 dark:bg-gray-900/30'
  if (matchType === 'ai_suggested') return 'bg-yellow-50 dark:bg-yellow-900/10'
  return ''
}
