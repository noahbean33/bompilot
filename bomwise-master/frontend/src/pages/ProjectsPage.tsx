import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { fetchProjects, cloneProject } from '../api/projects'
import { NewProjectModal } from '../components/NewProjectModal'

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function ProjectsPage() {
  const [showModal, setShowModal] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const { data: projects, isPending, isError } = useQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  const cloneMutation = useMutation({
    mutationFn: (id: number) => cloneProject(id),
    onSuccess: (newProject) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      navigate(`/projects/${newProject.id}`)
    },
  })

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900 dark:text-gray-100">Projects</h1>
        <button
          onClick={() => setShowModal(true)}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          New project
        </button>
      </div>

      {isPending && (
        <div className="flex justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
        </div>
      )}

      {isError && (
        <p className="py-8 text-center text-sm text-red-600 dark:text-red-400">
          Failed to load projects.
        </p>
      )}

      {projects && projects.length === 0 && (
        <div className="rounded-xl border-2 border-dashed border-gray-200 py-16 text-center dark:border-gray-700">
          <p className="text-gray-500 dark:text-gray-400">No projects yet.</p>
          <button
            onClick={() => setShowModal(true)}
            className="mt-4 text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
          >
            Create your first project →
          </button>
        </div>
      )}

      {projects && projects.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <div
              key={p.id}
              className="group rounded-xl bg-white p-5 shadow-sm ring-1 ring-gray-200 transition hover:ring-blue-400 dark:bg-gray-800 dark:ring-gray-700 dark:hover:ring-blue-500"
            >
              <Link to={`/projects/${p.id}`} className="block">
                <div className="flex items-start justify-between gap-2">
                  <h2 className="font-medium text-gray-900 group-hover:text-blue-700 dark:text-gray-100 dark:group-hover:text-blue-400">
                    {p.name}
                  </h2>
                  {p.variant_tag && (
                    <span className="shrink-0 rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500 dark:bg-gray-700 dark:text-gray-400">
                      {p.variant_tag}
                    </span>
                  )}
                </div>
                {p.description && (
                  <p className="mt-1 line-clamp-2 text-sm text-gray-500 dark:text-gray-400">{p.description}</p>
                )}
                <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">{formatDate(p.created_at)}</p>
              </Link>
              <div className="mt-3 border-t border-gray-100 pt-3 dark:border-gray-700">
                <button
                  onClick={(e) => {
                    e.preventDefault()
                    cloneMutation.mutate(p.id)
                  }}
                  disabled={cloneMutation.isPending && cloneMutation.variables === p.id}
                  className="text-xs text-gray-400 hover:text-blue-600 disabled:opacity-50 dark:text-gray-500 dark:hover:text-blue-400"
                >
                  {cloneMutation.isPending && cloneMutation.variables === p.id
                    ? 'Cloning…'
                    : 'Clone project'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showModal && <NewProjectModal onClose={() => setShowModal(false)} />}
    </div>
  )
}
