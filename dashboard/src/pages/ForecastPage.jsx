import { useMemo, useState } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Legend,
} from 'recharts'
import ChartTooltip from '../components/ChartTooltip'
import WeekCalendar from '../components/WeekCalendar'
import { datesOf, hourlyForDay, daySummaries, siteTotalsForDay } from '../utils/forecastMath'
import { SITES, TOTAL_CAPACITY } from '../config/sites'
import { useActivations } from '../context/ActivationsContext'
import { fmtMwh, fmtDayNum, fmtHour, fmtMw } from '../utils/format'

const ALL_SITES = 'all'

export default function ForecastPage({ rows }) {
  const { factors, activeCapacity, activeSites } = useActivations()
  const dates = useMemo(() => datesOf(rows), [rows])
  const [siteId, setSiteId] = useState(ALL_SITES)
  const [mode, setMode] = useState('jour') // jour | demain | semaine
  const [selectedDate, setSelectedDate] = useState(dates[0])

  const summaries = useMemo(() => daySummaries(rows), [rows])

  const focusDate = mode === 'semaine' ? null : mode === 'demain' ? dates[1] : selectedDate

  const hourly = useMemo(() => hourData(rows, focusDate, siteId), [rows, focusDate, siteId])

  const dailyAll = useMemo(
    () =>
      summaries.map((s) => {
        const row = { date: fmtDayNum(s.date), total: +s.total.toFixed(1) }
        SITES.forEach((site) => {
          row[site.id] = +(s.perSite[site.id] ?? 0).toFixed(1)
        })
        return row
      }),
    [summaries]
  )

  const selectedLabel = siteId === ALL_SITES ? 'Toutes les centrales' : SITES.find((s) => s.id === siteId)?.name

  const tomorrowPerSite = useMemo(
    () =>
      SITES.map((s) => {
        const { total, peak } = siteTotalsForDay(rows, dates[1], s.id)
        const active = s.capacity * ((factors[s.id] ?? 100) / 100)
        return { ...s, total, peak, factor: factors[s.id] ?? 100, pct: Math.min(100, Math.round((peak / (active || 1)) * 100)) }
      }).sort((a, b) => b.total - a.total),
    [rows, dates, factors]
  )

  const selectedSite = SITES.find((s) => s.id === siteId)
  const siteTomorrow = useMemo(
    () => (siteId === ALL_SITES ? null : tomorrowPerSite.find((s) => s.id === siteId) ?? null),
    [tomorrowPerSite, siteId]
  )

  return (
    <div className="space-y-6">
      <section className="card p-6 animate-fade-up">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-extrabold text-ink">Prévisions de production</h1>
            <p className="text-sm font-medium text-ink/50">
              Horizon J+1 → J+7 — {dates.length} jours de prévision horaire
            </p>
          </div>
          <div>
            <span className="chip bg-energy-50 text-energy-600 ring-1 ring-energy-200">
              ⚡ {fmtMwh(summaries.reduce((a, s) => a + s.total, 0))} sur l’horizon
            </span>
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <div className="flex rounded-xl bg-ink/5 p-1">
            {[
              ['jour', 'Aujourd’hui'],
              ['demain', 'Demain'],
              ['semaine', '7 jours'],
            ].map(([key, label]) => (
              <button
                key={key}
                onClick={() => {
                  setMode(key)
                  if (key === 'jour') setSelectedDate(dates[0])
                }}
                className={`rounded-lg px-4 py-1.5 text-sm font-semibold transition-all duration-200 ${
                  mode === key ? 'bg-white text-steg-700 shadow-card' : 'text-ink/55 hover:text-ink'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <select
            value={siteId}
            onChange={(e) => setSiteId(e.target.value)}
            className="rounded-xl border border-ink/10 bg-white px-4 py-2 text-sm font-semibold text-ink shadow-sm outline-none transition-all focus:border-steg-400 focus:ring-4 focus:ring-steg-400/15"
          >
            <option value={ALL_SITES}>Toutes les centrales</option>
            {SITES.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} — {s.city}
              </option>
            ))}
          </select>

          {mode !== 'semaine' && (
            <div className="flex flex-wrap gap-2">
              {dates.map((d) => (
                <button
                  key={d}
                  onClick={() => {
                    setSelectedDate(d)
                    setMode('jour')
                  }}
                  className={`rounded-xl px-3.5 py-2 text-xs font-bold transition-all duration-200 ${
                    (mode === 'demain' ? dates[1] : selectedDate) === d
                      ? 'bg-steg-600 text-white shadow-md shadow-steg-600/25'
                      : 'bg-ink/5 text-ink/60 hover:bg-steg-50 hover:text-steg-700'
                  }`}
                >
                  {fmtDayNum(d)}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      {mode !== 'semaine' && focusDate && (
        <section className="card p-6 animate-fade-up" style={{ animationDelay: '80ms' }}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-extrabold text-ink">
                Profil horaire — {selectedLabel}
              </h2>
              <p className="text-xs font-medium text-ink/50">
                {fmtDayNum(focusDate)} · énergie totale :{' '}
                {fmtMwh(hourly.reduce((a, h) => a + h.mw, 0))}
              </p>
            </div>
            <span className="chip bg-emerald-50 text-emerald-700 ring-1 ring-emerald-100">
              Pic à {fmtHour(hourly.reduce((best, h) => (h.mw > best.mw ? h : best), hourly[0])?.hour ?? 12)}
            </span>
          </div>
          <ResponsiveContainer width="100%" height={340}>
            <AreaChart key={`${siteId}-${focusDate}`} data={hourly} margin={{ top: 6, right: 8, left: -12, bottom: 0 }}>
              <defs>
                <linearGradient id="gradForecast" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3386f5" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#3386f5" stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 6" stroke="#e4eaf3" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#7c8aa0' }} interval={2} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: '#7c8aa0' }} axisLine={false} tickLine={false} domain={siteId === ALL_SITES ? [0, 60] : [0, 12]} />
              <Tooltip content={<ChartTooltip />} cursor={{ stroke: '#3386f5', strokeDasharray: '4 4' }} />
              <Area
                type="monotone"
                dataKey="mw"
                name="Production"
                stroke="#3386f5"
                strokeWidth={2.5}
                fill="url(#gradForecast)"
                animationDuration={1300}
                activeDot={{ r: 5, strokeWidth: 2, stroke: '#fff' }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </section>
      )}

      {mode !== 'semaine' && (
        <section className="card p-6 animate-fade-up" style={{ animationDelay: '160ms' }}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="text-base font-extrabold text-ink">Prévisions de demain</h2>
              <p className="text-xs font-medium text-ink/50">
                {siteId === ALL_SITES
                  ? 'Par centrale — énergie attendue'
                  : `${selectedSite?.name} — ${selectedSite?.city}`}
              </p>
            </div>
            <span className="chip bg-energy-50 text-energy-600 ring-1 ring-energy-200">
              {fmtMwh(
                siteId === ALL_SITES
                  ? tomorrowPerSite.reduce((a, s) => a + s.total, 0)
                  : siteTomorrow?.total ?? 0
              )} attendus
            </span>
          </div>

          {siteId === ALL_SITES || !selectedSite ? (
            <div className="grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-2">
              {tomorrowPerSite.map((s, i) => (
                <div key={s.id} className="group">
                  <div className="mb-1 flex items-center justify-between text-sm">
                    <span className="flex items-center gap-2 font-semibold text-ink">
                      <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                      {s.name}
                      <span className="text-[11px] font-medium text-ink/40">{s.city}</span>
                      {s.factor < 100 && (
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${s.factor === 0 ? 'bg-red-50 text-red-500' : 'bg-energy-50 text-energy-600'}`}>
                          {s.factor === 0 ? 'OFF' : `${s.factor} %`}
                        </span>
                      )}
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
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl bg-steg-50/60 p-5 ring-1 ring-steg-100">
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40">Énergie attendue</p>
                <p className="mt-1 text-3xl font-black text-steg-700">{fmtMwh(siteTomorrow?.total ?? 0)}</p>
              </div>
              <div className="rounded-xl bg-steg-50/60 p-5 ring-1 ring-steg-100">
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40">Pic de production</p>
                <p className="mt-1 text-3xl font-black text-ink">{fmtMw(siteTomorrow?.peak ?? 0)}</p>
              </div>
              <div className="rounded-xl bg-steg-50/60 p-5 ring-1 ring-steg-100">
                <p className="text-[11px] font-bold uppercase tracking-wide text-ink/40">Capacité utilisée</p>
                <p className="mt-1 text-3xl font-black text-energy-500">{siteTomorrow?.pct ?? 0} %</p>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-ink/8">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-steg-400 to-energy-500"
                    style={{ width: `${siteTomorrow?.pct ?? 0}%` }}
                  />
                </div>
              </div>
            </div>
          )}
        </section>
      )}

      {mode === 'semaine' && (
        <section className="space-y-4">
          <div className="card p-6 animate-fade-up" style={{ animationDelay: '100ms' }}>
            <h2 className="text-base font-extrabold text-ink">Comparaison quotidienne</h2>
            <p className="text-xs font-medium text-ink/50">Production attendue par jour (MW)</p>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={dailyAll} margin={{ top: 6, right: 8, left: -8, bottom: 0 }} barCategoryGap="30%">
                <CartesianGrid strokeDasharray="3 6" stroke="#e4eaf3" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#7c8aa0' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#7c8aa0' }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltip unit="MW" />} cursor={{ fill: 'rgba(51,134,245,0.06)' }} />
                <Legend wrapperStyle={{ fontSize: 11, fontWeight: 600 }} />
                {SITES.map((s) => (
                  <Bar key={s.id} dataKey={s.id} name={s.name} stackId="a" fill={s.color} radius={[3, 3, 0, 0]} animationDuration={1200} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card p-6 animate-fade-up" style={{ animationDelay: '180ms' }}>
          <h2 className="text-base font-extrabold text-ink">Calendrier des prévisions</h2>
          <p className="text-xs font-medium text-ink/50">Énergie attendue par jour — profil horaire</p>
          <div className="mt-4">
            <WeekCalendar rows={rows} dates={dates} summaries={summaries} />
          </div>
        </div>
      </section>
    )}

      <div className="card p-5 animate-fade-up" style={{ animationDelay: '220ms' }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm font-semibold text-ink/60">
            Capacité installée totale : <span className="font-extrabold text-ink">{TOTAL_CAPACITY} MW</span> ·{' '}
            <span className="font-extrabold text-steg-700">{fmtMw(activeCapacity)} actifs</span> ·{' '}
            {activeSites} / {SITES.length} centrales en service
          </p>
          <p className="text-xs font-medium text-ink/40">
            Données de prévision — mise à jour quotidienne
          </p>
        </div>
      </div>
    </div>
  )
}

function hourData(rows, date, siteId) {
  return hourlyForDay(rows, date, siteId === ALL_SITES ? null : siteId)
}