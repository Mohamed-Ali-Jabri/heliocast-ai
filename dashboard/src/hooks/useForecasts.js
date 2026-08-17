import { useCallback, useEffect, useState } from 'react'
import { fetchForecasts } from '../api/client'
import { toRows } from '../utils/forecastMath'

export function useForecasts() {
  const [state, setState] = useState({ loading: true, error: null, rows: [], meta: null })

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }))
    try {
      const json = await fetchForecasts()
      setState({ loading: false, error: null, rows: toRows(json), meta: json })
    } catch (err) {
      setState((s) => ({ ...s, loading: false, error: err.message }))
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return { ...state, reload: load }
}