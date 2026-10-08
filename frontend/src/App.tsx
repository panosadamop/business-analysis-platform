import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { Shell } from './components/Shell'
import { Spinner } from './components/ui'
import { useSession } from './lib/store'
import { AdminPage } from './pages/AdminPage'
import { AnalysisPage } from './pages/AnalysisPage'
import { ApprovalsPage } from './pages/ApprovalsPage'
import { BacklogPage } from './pages/BacklogPage'
import { ClientPage } from './pages/ClientPage'
import { DashboardsPage } from './pages/DashboardsPage'
import { EvidencePage } from './pages/EvidencePage'
import { IntegrationsPage } from './pages/IntegrationsPage'
import { LoginPage } from './pages/LoginPage'
import { PlanningPage } from './pages/PlanningPage'
import { PortfolioPage } from './pages/PortfolioPage'
import { ReportsPage } from './pages/ReportsPage'
import { SharingPage } from './pages/SharingPage'
import { SpecificationsPage } from './pages/SpecificationsPage'
import { ProjectSetupPage } from './pages/ProjectSetupPage'
import { TestbookPage } from './pages/TestbookPage'

export default function App() {
  const { status, restore, user } = useSession()
  const location = useLocation()

  useEffect(() => {
    if (status === 'unknown') void restore()
  }, [status, restore])

  if (status === 'unknown') {
    return <div className="p-8"><Spinner /></div>
  }

  if (status === 'anonymous') {
    return (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace state={{ from: location }} />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/" replace />} />
      <Route element={<Shell />}>
        <Route path="/" element={user?.isClient
          ? <Navigate to="/client" replace />
          : <PortfolioPage />} />
        <Route path="/client" element={<ClientPage />} />
        <Route path="/client/:projectId" element={<ClientPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/projects/:projectId">
          <Route index element={<Navigate to="evidence" replace />} />
          <Route path="setup" element={<ProjectSetupPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="backlog" element={<BacklogPage />} />
          <Route path="specifications" element={<SpecificationsPage />} />
          <Route path="approvals" element={<ApprovalsPage />} />
          <Route path="planning" element={<PlanningPage />} />
          <Route path="testbook" element={<TestbookPage />} />
          <Route path="dashboards" element={<DashboardsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="integrations" element={<IntegrationsPage />} />
          <Route path="sharing" element={<SharingPage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
