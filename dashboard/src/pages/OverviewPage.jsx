import { useMemo, useState } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine, ReferenceDot,
} from 'recharts'
import StatCard from '../components/StatCard'
import WeatherIcon from '../components/WeatherIcon'
import ChartTooltip from '../components/ChartTooltip'
import AnimatedNumber from '../components/AnimatedNumber'
import { datesOf, hourlyForDay, siteTotalsForDay, daySummaries } from '../utils/forecastMath'
import { SITES } from '../config/sites'
import { useActivations } from '../context/ActivationsContext'
import { fmtMwh, fmtMw, fmtHour, fmtDateLong } from '../utils/format'

export default function OverviewPage({ rows }) {
  const { factors, setFactor, toggle, setAll, activeCapacity, activeSites } = useActivations()

  const dates = useMemo(() => datesOf(rows), [rows])
  const today = dates[0]
  const tomorrow = dates[1]
  const [showPeak, setShowPeak] = useState(false)

  const todayTotals = useMemo(() => siteTotalsForDay(rows, today), [rows, today])
  const tomorrowTotals = useMemo(() => siteTotalsForDay(rows, tomorrow), [rows, tomorrow])
  const hourly = useMemo(() => hourlyForDay(rows, today), [rows, today])
  const summaries = useMemo(() => daySummaries(rows), [rows])
  const todaySummary = summaries.find((s) => s.date === today)

  const perSiteToday = useMemo(
    () =>
      SITES.map((s) => {
        const { total, peak } = siteTotalsForDay(rows, today, s.id)
        const active = s.capacity * ((factors[s.id] ?? 100) / 100)
        return { ...s, total, peak, pct: Math.min(100, Math.round((peak / (active || 1)) * 100)) }
      }).sort((a, b) => b.total - a.total),
    [rows, today, factors]
  )

  return (
    <div className="space-y-6">
      {/* Héro */}
      <section className="card relative overflow-hidden p-6 animate-fade-up">
        <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-gradient-to-br from-energy-400/25 to-transparent blur-2xl" />
        <div className="pointer-events-none absolute -bottom-20 left-1/3 h-52 w-52 rounded-full bg-steg-400/15 blur-2xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-5">
            <div className="grid h-16 w-16 place-items-center rounded-2xl bg-gradient-to-br from-steg-500 to-steg-700 shadow-lg shadow-steg-600/30 animate-floaty">
              <WeatherIcon kind="soleil" size={38} />
            </div>
            <div>
              <p className="text-xs font-bold uppercase tracking-widest text-steg-600">
                Production attendue — {fmtDateLong(today)}
              </p>
              <p className="mt-1 text-4xl font-black tracking-tight text-ink">
                <AnimatedNumber value={todayTotals.total} format={fmtMwh} />
              </p>
              <p className="mt-1 text-sm font-medium text-ink/55">
                <button
                  type="button"
                  onClick={() => setShowPeak((v) => !v)}
                  className={`cursor-pointer rounded-lg px-2 py-0.5 font-medium transition-all duration-200 ${
                    showPeak ? 'bg-orange-100 text-orange-600 ring-1 ring-orange-300' : 'hover:bg-ink/5 hover:text-ink/80'
                  }`}
                  title="Cliquer pour afficher le pic sur la courbe"
                >
                  Pic estimé à {fmtHour(todaySummary?.peakHour ?? 12)} ·{' '}
                  <AnimatedNumber value={todayTotals.peak} format={fmtMw} />
                </button>
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="card-glass flex items-center gap-3 px-5 py-3">
              <div className="grid h-9 w-9 place-items-center rounded-xl bg-energy-50 text-lg">⚡</div>
              <div>
                <p className="text-sm font-extrabold text-ink">
                  <AnimatedNumber value={tomorrowTotals?.total ?? 0} format={fmtMwh} />
                </p>
                <p className="text-xs font-medium text-ink/50">Prévu demain</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Cartes statistiques */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Production aujourd’hui"
          value={todayTotals.total}
          format={fmtMwh}
          accent="blue"
          sub={`Pic à ${fmtMw(todayTotals.peak)}`}
          icon={<WeatherIcon kind="soleil" size={24} />}
          delay={0}
        />
        <StatCard
          title="Production demain"
          value={tomorrowTotals?.total ?? 0}
          format={fmtMwh}
          accent="orange"
          sub={`Après-demain : ${fmtMwh(siteTotalsForDay(rows, dates[2]).total)}`}
          icon={<WeatherIcon kind="partiel" size={24} />}
          delay={80}
        />
        <StatCard
          title="Heure de pointe"
          value={todaySummary?.peakHour ?? 12}
          format={(v) => fmtHour(Math.round(v))}
          accent="green"
          sub={`Pic ${fmtMw(todaySummary?.peak ?? 0)} — Moment de production maximale`}
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M13 2 4.5 13.5H11L9.5 22 19 10h-6.5L13 2z" />
            </svg>
          }
          delay={160}
        />
        <StatCard
          title="Centrales actives"
          value={activeSites}
          format={(v) => `${Math.round(v)} / ${SITES.length}`}
          accent="violet"
          sub={`${fmtMw(activeCapacity)} disponibles`}
          icon={
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M12 2v6M12 6l5 3M12 6 7 9M7 15a5 5 0 0 0 10 0" />
            </svg>
          }
          delay={240}
        />
      </section>

      {/* Courbe du jour + nuages */}
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="card p-6 xl:col-span-2 animate-fade-up" style={{ animationDelay: '120ms' }}>
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-base font-extrabold text-ink">Profil de production — aujourd’hui</h2>
              <p className="text-xs font-medium text-ink/50">Prévision horaire toutes centrales confondues</p>
            </div>
            <span className="chip bg-steg-50 text-steg-700">{fmtMwh(todayTotals.total)} attendus</span>
          </div>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={hourly} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="gradDay" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3386f5" stopOpacity={0.42} />
                  <stop offset="100%" stopColor="#3386f5" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 6" stroke="#e4eaf3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#7c8aa0' }} interval={2} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#7c8aa0' }} axisLine={false} tickLine={false} />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#3386f5', strokeDasharray: '4 4' }} />
              <Area
                type="monotone"
                dataKey="mw"
                name="Production"
                stroke="#3386f5"
                strokeWidth={2.5}
                fill="url(#gradDay)"
                animationDuration={1400}
                activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
              />
              {showPeak && todaySummary && hourly[todaySummary.peakHour] && (
                <>
                  <ReferenceLine
                    x={hourly[todaySummary.peakHour].label}
                    stroke="#f97316"
                    strokeDasharray="4 4"
                    strokeWidth={1.5}
                  />
                  <ReferenceDot
                    x={hourly[todaySummary.peakHour].label}
                    y={hourly[todaySummary.peakHour].mw}
                    r={6}
                    fill="#f97316"
                    stroke="#fff"
                    strokeWidth={2}
                    label={{
                      value: `Pic ${fmtMw(hourly[todaySummary.peakHour].mw)}`,
                      position: 'top',
                      fill: '#f97316',
                      fontSize: 12,
                      fontWeight: 700,
                    }}
                  />
                </>
              )}
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card p-6 animate-fade-up" style={{ animationDelay: '200ms' }}>
          <h2 className="text-base font-extrabold text-ink">Répartition par centrale</h2>
          <p className="text-xs font-medium text-ink/50">Aujourd’hui — énergie attendue</p>
          <div className="mt-4 space-y-4">
            {perSiteToday.map((s, i) => (
              <div key={s.id} className="group">
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="flex items-center gap-2 font-semibold text-ink">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                    {s.name}
                    <span className="text-[11px] font-medium text-ink/40">{s.city}</span>
                  </span>
                  <span className="font-bold text-ink/75">{fmtMwh(s.total)}</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-ink/8">
                  <div
                    className="h-full rounded-full transition-all duration-1000 ease-out"
                    style={{
                      width: `${s.pct}%`,
                      background: `linear-gradient(90deg, ${s.color}, ${s.color}99)`,
                      animationDelay: `${i * 90}ms`,
                    }}
                  />
                </div>
                <p className="mt-1 text-right text-[11px] font-medium text-ink/40">
                  Pic {fmtMw(s.peak)} · {s.pct} % de la capacité active
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}