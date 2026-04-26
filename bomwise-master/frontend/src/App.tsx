import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from './context/ThemeContext'
import { AdminLayout } from './components/AdminLayout'
import { AuthInitializer } from './components/AuthInitializer'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { AdminProvidersPage } from './pages/AdminProvidersPage'
import { AdminStatsPage } from './pages/AdminStatsPage'
import { AdminUsersPage } from './pages/AdminUsersPage'
import { AdminUserDetailPage } from './pages/AdminUserDetailPage'
import { AdminAiPage } from './pages/AdminAiPage'
import { AdminSettingsPage } from './pages/AdminSettingsPage'
import { ForgotPasswordPage } from './pages/ForgotPasswordPage'
import { LoginPage } from './pages/LoginPage'
import { SignupPage } from './pages/SignupPage'
import { PreferencesPage } from './pages/PreferencesPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { ResetPasswordPage } from './pages/ResetPasswordPage'
import { VariantsPage } from './pages/VariantsPage'
import { ManualSearchPage } from './pages/ManualSearchPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

function App() {
  return (
    <ThemeProvider>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthInitializer>
          <Routes>
            {/* Public auth routes */}
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/forgot-password" element={<ForgotPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />

            {/* All authenticated routes share ProtectedRoute → Layout */}
            <Route element={<ProtectedRoute />}>
              <Route element={<Layout />}>
                <Route index element={<Navigate to="/projects" replace />} />
                <Route path="/projects" element={<ProjectsPage />} />
                <Route path="/projects/:id" element={<ProjectDetailPage />} />
                <Route
                  path="/projects/:id/bom/:lineId/variants"
                  element={<VariantsPage />}
                />
                <Route
                  path="/projects/:id/bom/:lineId/search"
                  element={<ManualSearchPage />}
                />
                <Route path="/preferences" element={<PreferencesPage />} />
                {/* /settings/billing redirects to preferences billing tab */}
                <Route
                  path="/settings/billing"
                  element={<Navigate to="/preferences?tab=billing" replace />}
                />

                {/* Admin section — AdminLayout handles the is_admin guard */}
                <Route path="/admin" element={<AdminLayout />}>
                  <Route index element={<Navigate to="/admin/providers" replace />} />
                  <Route path="providers" element={<AdminProvidersPage />} />
                  <Route path="stats" element={<AdminStatsPage />} />
                  <Route path="users" element={<AdminUsersPage />} />
                  <Route path="users/:userId" element={<AdminUserDetailPage />} />
                  <Route path="ai" element={<AdminAiPage />} />
                  <Route path="settings" element={<AdminSettingsPage />} />
                </Route>
              </Route>
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AuthInitializer>
      </BrowserRouter>
    </QueryClientProvider>
    </ThemeProvider>
  )
}

export default App
