import axios from 'axios'
import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { importBom } from '../api/bom'

interface Props {
  projectId: number
}

export function CsvImport({ projectId }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastCount, setLastCount] = useState<number | null>(null)
  const queryClient = useQueryClient()

  async function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setError(null)
    setLastCount(null)
    setUploading(true)

    try {
      const result = await importBom(projectId, file)
      setLastCount(result.imported)
      await queryClient.invalidateQueries({ queryKey: ['bom', projectId] })
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail
        if (detail?.error === 'plan_limit_exceeded') {
          setError(`Import failed: your plan allows at most ${detail.max} parts per project (file has more).`)
        } else if (typeof detail === 'string') {
          setError(`Import failed: ${detail}`)
        } else {
          setError(`Import failed (HTTP ${err.response?.status ?? '?'}). Make sure the file is a valid CSV.`)
        }
      } else {
        setError('Import failed. Make sure the file is a valid CSV.')
      }
    } finally {
      setUploading(false)
      // reset so the same file can be re-selected
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className="flex items-center gap-3">
      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={handleFile}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {uploading ? (
          <>
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            Importing…
          </>
        ) : (
          'Import CSV'
        )}
      </button>

      {lastCount !== null && (
        <span className="text-sm text-green-600">{lastCount} lines imported</span>
      )}
      {error && <span className="text-sm text-red-600">{error}</span>}
    </div>
  )
}
