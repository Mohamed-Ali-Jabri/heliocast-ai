// Unique point d'accès aux données. Consomme uniquement GET /forecasts/latest.
export async function fetchForecasts() {
  const res = await fetch('/forecasts/latest', { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`Impossible de charger les prévisions (HTTP ${res.status})`)
  }
  return res.json()
}

// Lance une nouvelle prévision : les anciennes données sont supprimées en base.
export async function refreshForecasts() {
  const res = await fetch('/forecasts/refresh', { method: 'POST', headers: { Accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`Impossible de générer les prévisions (HTTP ${res.status})`)
  }
  return res.json()
}