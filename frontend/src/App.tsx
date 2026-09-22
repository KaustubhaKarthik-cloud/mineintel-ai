import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequirePermission } from './auth/RequirePermission'
import { AppLayout } from './components/AppLayout'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { AssistantPage } from './pages/AssistantPage'
import { AuditPage } from './pages/AuditPage'
import { DashboardPage } from './pages/DashboardPage'
import { DocumentDetailPage } from './pages/DocumentDetailPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { ExplorerPage } from './pages/ExplorerPage'
import { GeologicalExplorerPage } from './pages/GeologicalExplorerPage'
import { LoginPage } from './pages/LoginPage'
import { ReportsPage } from './pages/ReportsPage'
import { ReportDetailPage } from './pages/ReportDetailPage'
import { ReviewPage } from './pages/ReviewPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { TopicsPage } from './pages/TopicsPage'
import { UploadPage } from './pages/UploadPage'
import { UsersPage } from './pages/UsersPage'
import { ValidationPage } from './pages/ValidationPage'

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<AppLayout />}>
            <Route index element={<DashboardPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="documents/:id" element={<DocumentDetailPage />} />
            <Route path="upload" element={<UploadPage />} />
            <Route
              path="review"
              element={
                <RequirePermission permission="review.act">
                  <ReviewPage />
                </RequirePermission>
              }
            />
            <Route
              path="validation"
              element={
                <RequirePermission permission="validation.act">
                  <ValidationPage />
                </RequirePermission>
              }
            />
            <Route path="search" element={<SearchPage />} />
            <Route path="explorer" element={<ExplorerPage />} />
            <Route path="geology" element={<GeologicalExplorerPage />} />
            <Route path="assistant" element={<AssistantPage />} />
            <Route path="analytics" element={<AnalyticsPage />} />
            <Route path="topics" element={<TopicsPage />} />
            <Route path="reports" element={<ReportsPage />} />
            <Route path="reports/:id" element={<ReportDetailPage />} />
            <Route
              path="audit"
              element={
                <RequirePermission permission="audit.read">
                  <AuditPage />
                </RequirePermission>
              }
            />
            <Route
              path="users"
              element={
                <RequirePermission permission="users.manage">
                  <UsersPage />
                </RequirePermission>
              }
            />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
