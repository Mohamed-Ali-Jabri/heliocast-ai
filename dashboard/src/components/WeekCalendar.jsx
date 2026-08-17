import { useMemo } from 'react'
import { hourlyForDay } from '../utils/forecastMath'
import { fmtMwh, fmtMw, fmtHour, fmtDateShort } from '../utils/format'

export default function WeekCalendar({ rows, dates, summaries }) {
  const days = useMemo(
    () =>
      dates.map((d) => {
        const summary = summaries.find((s) => s.date === d)
        const hourly = hourlyForDay(rows, d)
        const maxH = Math.max(...hourly.map((h) => h.mw), 0.0001)
        return {
          date: d,
          label: fmtDateShort(d),
          total: summary?.total ?? 0,
          peak: summary?.peak ?? 0,
          peakHour: summary?.peakHour ?? 12,
          hourly,
          maxH,
        }
      }),
    [rows, dates, summaries]
  )

  if (days.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-7">
      {days.map((day) => (
        <div key={day.date} className="card p-4">
          <p className="text-xs font-bold uppercase tracking-wide text-steg-600">{day.label}</p>
          <p className="mt-1 text-lg font-black tracking-tight text-ink">{fmtMwh(day.total)}</p>
          <p className="text-[11px] font-medium text-ink/45">
            Pic {fmtMw(day.peak)} à {fmtHour(day.peakHour)}
          </p>
          <div className="mt-3 flex h-14 items-end gap-[2px]">
            {day.hourly.map((h, i) => (
              <div
                key={i}
                title={`${h.label} : ${fmtMw(h.mw)}`}
                className="flex-1 rounded-sm bg-gradient-to-t from-steg-500 to-energy-400"
                style={{
                  height: `${Math.max(4, (h.mw / day.maxH) * 100)}%`,
                  opacity: h.mw > 0 ? 0.4 + 0.6 * (h.mw / day.maxH) : 0.08,
                }}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}