// Dérivations métier à partir des lignes (site_id, date, hour, mw).
import { TOTAL_CAPACITY, DAYLIGHT_HOURS } from '../config/sites'

export function toRows(json) {
  return (json.data || []).map((d) => ({
    site_id: d.site_id,
    date: d.timestamp.slice(0, 10),
    hour: Number(d.timestamp.slice(11, 13)),
    mw: Number(d.prediction_mw),
  }))
}

export function datesOf(rows) {
  return [...new Set(rows.map((r) => r.date))].sort()
}

export function siteTotalsForDay(rows, date, siteId = null) {
  const sel = rows.filter((r) => r.date === date && (siteId === null || r.site_id === siteId))
  const total = sel.reduce((a, r) => a + r.mw, 0)
  const peak = sel.reduce((m, r) => Math.max(m, r.mw), 0)
  return { total, peak }
}

export function hourlyForDay(rows, date, siteId = null) {
  const byHour = {}
  rows.forEach((r) => {
    if (r.date === date && (siteId === null || r.site_id === siteId)) {
      byHour[r.hour] = (byHour[r.hour] || 0) + r.mw
    }
  })
  return Array.from({ length: 24 }, (_, h) => ({
    hour: h,
    label: `${String(h).padStart(2, '0')}h`,
    mw: +(byHour[h] ?? 0).toFixed(2),
  }))
}

export function daySummaries(rows) {
  const dates = datesOf(rows)
  return dates.map((date) => {
    const perSite = {}
    let total = 0
    let peak = 0
    let peakHour = 6
    const byHour = {}
    rows.forEach((r) => {
      if (r.date !== date) return
      total += r.mw
      perSite[r.site_id] = (perSite[r.site_id] || 0) + r.mw
      byHour[r.hour] = (byHour[r.hour] || 0) + r.mw
    })
    Object.entries(byHour).forEach(([h, v]) => {
      if (v > peak) {
        peak = v
        peakHour = Number(h)
      }
    })
    return { date, total, peak, peakHour, perSite }
  })
}

export function weatherKind(peakMw, capacity = 60) {
  const cf = capacity > 0 ? peakMw / capacity : 0
  if (cf >= 0.6) return { kind: 'soleil', label: 'Ciel ensoleillé' }
  if (cf >= 0.3) return { kind: 'partiel', label: 'Partiellement nuageux' }
  return { kind: 'nuageux', label: 'Ciel nuageux' }
}

export function skyFromRows(rows) {
  const sums = datesOf(rows).map((d) => siteTotalsForDay(rows, d).total)
  const mean = sums.length ? sums.reduce((a, b) => a + b, 0) / sums.length : 0
  const cf = mean / (TOTAL_CAPACITY * DAYLIGHT_HOURS)
  if (cf >= 0.55) return { kind: 'soleil', label: 'Ensoleillé' }
  if (cf >= 0.35) return { kind: 'partiel', label: 'Variable' }
  return { kind: 'nuageux', label: 'Couvert' }
}