import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { SITES } from '../config/sites'

const STORAGE_KEY = 'heliocast-activations-v1'

const DEFAULT_FACTORS = Object.fromEntries(SITES.map((s) => [s.id, 100]))

function loadFactors() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_FACTORS
    const parsed = JSON.parse(raw)
    const factors = { ...DEFAULT_FACTORS }
    SITES.forEach((s) => {
      const v = Number(parsed[s.id])
      if (Number.isFinite(v)) factors[s.id] = Math.max(0, Math.min(100, Math.round(v)))
    })
    return factors
  } catch {
    return DEFAULT_FACTORS
  }
}

const ActivationsContext = createContext(null)

export function ActivationsProvider({ children }) {
  const [factors, setFactors] = useState(loadFactors)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(factors))
    } catch {
      // stockage indisponible — l'état reste en mémoire
    }
  }, [factors])

  const setFactor = (siteId, pct) => {
    setFactors((f) => ({ ...f, [siteId]: Math.max(0, Math.min(100, Math.round(Number(pct) || 0))) }))
  }

  const toggle = (siteId) => {
    setFactors((f) => ({ ...f, [siteId]: f[siteId] > 0 ? 0 : 100 }))
  }

  const setAll = (pct) => {
    const v = Math.max(0, Math.min(100, Math.round(Number(pct) || 0)))
    setFactors(Object.fromEntries(SITES.map((s) => [s.id, v])))
  }

  const value = useMemo(() => {
    const activeCapacity = SITES.reduce((a, s) => a + s.capacity * (factors[s.id] / 100), 0)
    const activeSites = SITES.filter((s) => factors[s.id] > 0).length
    return { factors, setFactor, toggle, setAll, activeCapacity, activeSites }
  }, [factors])

  return <ActivationsContext.Provider value={value}>{children}</ActivationsContext.Provider>
}

export function useActivations() {
  const ctx = useContext(ActivationsContext)
  if (!ctx) throw new Error('useActivations doit être utilisé dans <ActivationsProvider>')
  return ctx
}
