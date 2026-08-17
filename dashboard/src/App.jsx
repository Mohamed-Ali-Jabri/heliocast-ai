import { useMemo } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import OverviewPage from './pages/OverviewPage'
import ForecastPage from './pages/ForecastPage'
import ActivationsPage from './pages/ActivationsPage'
import { useForecasts } from './hooks/useForecasts'
import { ActivationsProvider, useActivations } from './context/ActivationsContext'
import { FullScreenLoading, ErrorState } from './components/LoadingState'

function RoutedApp({ rows }) {
  const { factors } = useActivations()

  const scaledRows = useMemo(
    () =>
      rows.map((r) => ({
        ...r,
        mw: r.mw * ((factors[r.site_id] ?? 100) / 100),
      })),
    [rows, factors]
  )

  return (
    <Routes>
      <Route path="/" element={<OverviewPage rows={scaledRows} />} />
      <Route path="/previsions" element={<ForecastPage rows={scaledRows} />} />
      <Route path="/centrales" element={<ActivationsPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  const { loading, error, rows, meta, reload } = useForecasts()

  if (loading) return <FullScreenLoading />
  if (error || rows.length === 0) {
    return <ErrorState message={error || 'Aucune prévision disponible pour le moment.'} onRetry={reload} />
  }

  const generatedAt = meta?.generated_at

  return (
    <HashRouter>
      <ActivationsProvider>
        <Layout generatedAt={generatedAt} onRefresh={reload}>
          <RoutedApp rows={rows} />
        </Layout>
      </ActivationsProvider>
    </HashRouter>
  )
}