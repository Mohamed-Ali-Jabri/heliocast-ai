const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0)

export const fmtMw = (v) =>
  `${num(v).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} MW`

export const fmtMwh = (v) =>
  `${num(v).toLocaleString('fr-FR', { maximumFractionDigits: 1 })} MW`

export const fmtHour = (h) => `${String(h).padStart(2, '0')}h`

export const fmtDateLong = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

export const fmtDateShort = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })

export const fmtDayNum = (iso) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'short',
  })