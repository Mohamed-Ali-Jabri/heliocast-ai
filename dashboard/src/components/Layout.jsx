import { useEffect, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import WeatherIcon from './WeatherIcon'
import { refreshForecasts } from '../api/client'

const NAV = [
  { to: '/', label: 'Vue d’ensemble', icon: 'sun', end: true },
  { to: '/previsions', label: 'Prévisions', icon: 'chart' },
  { to: '/centrales', label: 'Centrales', icon: 'power' },
]

const ICONS = {
  sun: (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.5v2.4M12 19.1v2.4M2.5 12h2.4M19.1 12h2.4M5.3 5.3l1.7 1.7M17 17l1.7 1.7M18.7 5.3L17 7M7 17l-1.7 1.7" />
    </svg>
  ),
  chart: (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 20V10M10 20V4M16 20v-8M22 20H2" />
    </svg>
  ),
  power: (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M13 2 4.5 13.5H11L9.5 22 19 10h-6.5L13 2z" />
    </svg>
  ),
}

export default function Layout({ children, generatedAt = null, onRefresh = null }) {
  const [now, setNow] = useState(new Date())
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState(null)
  const location = useLocation()

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000)
    return () => clearInterval(t)
  }, [])

  const handleRefresh = async () => {
    if (refreshing) return
    setRefreshing(true)
    setRefreshError(null)
    try {
      await refreshForecasts()
      if (onRefresh) await onRefresh()
    } catch (err) {
      setRefreshError(err.message)
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-ink/5 bg-white/80 backdrop-blur lg:flex">
        <div className="flex items-center gap-3 px-6 pb-5 pt-6">
          <div className="grid h-11 w-11 place-items-center rounded-xl bg-gradient-to-br from-steg-500 to-steg-700 shadow-md shadow-steg-600/30">
            <WeatherIcon kind="soleil" size={26} />
          </div>
          <div>
            <p className="text-sm font-extrabold tracking-tight text-ink">HelioCast</p>
            <p className="text-[11px] font-semibold uppercase tracking-widest text-steg-600">
              Contrôle solaire STEG
            </p>
          </div>
        </div>

        <nav className="flex-1 space-y-1 px-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `group flex items-center gap-3 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-200 ${
                  isActive
                    ? 'bg-steg-600 text-white shadow-md shadow-steg-600/25'
                    : 'text-ink/60 hover:bg-steg-50 hover:text-steg-700'
                }`
              }
            >
              {ICONS[item.icon]}
              {item.label}
            </NavLink>
          ))}
        </nav>

        </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-ink/5 bg-white/70 px-6 py-4 backdrop-blur-md">
          <div>
            <p className="text-xl font-extrabold tracking-tight text-ink">
              Supervision photovoltaïque
            </p>
            <p className="text-xs font-medium capitalize text-ink/50">
              {now.toLocaleDateString('fr-FR', {
                weekday: 'long',
                day: 'numeric',
                month: 'long',
                year: 'numeric',
              })}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {generatedAt && (
              <div className="hidden items-center gap-2 rounded-full bg-emerald-50 px-4 py-2 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-100 sm:flex">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
                Mise à jour : {generatedAt}
              </div>
            )}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="btn-primary !px-4 !py-2 text-xs disabled:cursor-not-allowed disabled:opacity-60"
            >
              {refreshing ? 'Génération en cours…' : '🔄 Nouvelle prévision'}
            </button>
            {refreshError && (
              <span className="rounded-full bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-600 ring-1 ring-red-100">
                {refreshError}
              </span>
            )}
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-ink text-white">
              <WeatherIcon kind="soleil" size={20} animate={false} />
            </div>
          </div>
        </header>

        <main
          key={location.pathname}
          className="flex-1 animate-fade-in px-6 py-6 lg:px-8"
        >
          {children}
        </main>
      </div>
    </div>
  )
}