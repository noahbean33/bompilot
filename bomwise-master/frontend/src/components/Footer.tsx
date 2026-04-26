import { useQuery } from '@tanstack/react-query'
import { getVersion } from '../api/client'

export function Footer() {
  const { data: versionInfo } = useQuery({
    queryKey: ['version'],
    queryFn: getVersion,
    staleTime: 1000 * 60 * 60, // cache for 1 hour
  })

  const versionStr = versionInfo ? `v${versionInfo.version}` : ''
  const commitStr = versionInfo?.commit ? ` (${versionInfo.commit.slice(0, 7)})` : ''

  return (
    <footer className="border-t border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
      <div className="mx-auto max-w-7xl px-6 py-4">
        <div className="flex flex-col items-center justify-between gap-2 text-sm text-gray-500 dark:text-gray-400 md:flex-row">
          {/* Left: Brand + Version */}
          <div className="flex items-center gap-3">
            <span>BOMexplorer</span>
            {versionStr && (
              <span className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-gray-600 dark:bg-gray-800 dark:text-gray-300">
                {versionStr}{commitStr}
              </span>
            )}
          </div>

          {/* Center: Public links */}
          <div className="flex items-center gap-4">
            <a href="https://bomexplorer.app/about" className="hover:text-gray-700 dark:hover:text-gray-300">
              About
            </a>
            <a href="https://bomexplorer.app/features" className="hover:text-gray-700 dark:hover:text-gray-300">
              Features
            </a>
            <a href="https://bomexplorer.app/faq" className="hover:text-gray-700 dark:hover:text-gray-300">
              FAQ
            </a>
            <a href="https://bomexplorer.app/contact" className="hover:text-gray-700 dark:hover:text-gray-300">
              Contact
            </a>
          </div>

          {/* Right: Legal */}
          <div className="flex items-center gap-4">
            <a href="https://bomexplorer.app/privacy" className="hover:text-gray-700 dark:hover:text-gray-300">
              Privacy
            </a>
            <a href="https://bomexplorer.app/terms" className="hover:text-gray-700 dark:hover:text-gray-300">
              Terms
            </a>
          </div>
        </div>
      </div>
    </footer>
  )
}