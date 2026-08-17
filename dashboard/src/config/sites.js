// Informations d'exploitation des centrales (constantes métier réelles du projet).
export const SITES = [
  { id: 'tozeur_1', name: 'Tozeur 1', city: 'Tozeur', lat: 33.9086, lon: 8.0463, capacity: 10, color: '#f59e0b' },
  { id: 'tozeur_2', name: 'Tozeur 2', city: 'Tozeur', lat: 33.9086, lon: 8.0463, capacity: 10, color: '#f97316' },
  { id: 'meknassi_eppm', name: 'Meknassi EPPM', city: 'Kasserine', lat: 34.6054, lon: 9.6022, capacity: 10, color: '#0ea5e9' },
  { id: 'elmourabitine_eni', name: 'El Mourabitine ENI', city: 'Gabès', lat: 33.0502, lon: 10.4633, capacity: 10, color: '#10b981' },
  { id: 'feriana_csfb', name: 'Feriana CSFB', city: 'Feriana', lat: 34.8891, lon: 8.5530, capacity: 10, color: '#6366f1' },
  { id: 'feriana_csfc', name: 'Feriana CSFC', city: 'Feriana', lat: 34.8892, lon: 8.5534, capacity: 10, color: '#8b5cf6' },
]

export const SITE_BY_ID = Object.fromEntries(SITES.map((s) => [s.id, s]))
export const TOTAL_CAPACITY = SITES.reduce((a, s) => a + s.capacity, 0)
export const DAYLIGHT_HOURS = 12