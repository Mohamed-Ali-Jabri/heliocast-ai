import WeatherIcon from './WeatherIcon'
import { fetchForecasts } from '../api/client'

export function FullScreenLoading() {
  return (
    <div className="grid min-h-screen place-items-center bg-sand">
      <div className="flex flex-col items-center gap-6">
        <div className="relative animate-floaty">
          <div className="absolute -inset-5 rounded-full bg-energy-400/25 blur-xl animate-breath" />
          <WeatherIcon kind="partiel" size={84} />
        </div>
        <div className="h-1.5 w-52 overflow-hidden rounded-full bg-ink/10">
          <div className="h-full w-1/2 rounded-full bg-gradient-to-r from-steg-500 to-energy-500 animate-shimmer" />
        </div>
        <p className="text-sm font-semibold text-ink/55">
          Chargement des données solaires…
        </p>
      </div>
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="grid min-h-[60vh] place-items-center px-6">
      <div className="card max-w-md p-8 text-center animate-fade-up">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-xl bg-energy-50 text-3xl">
          ☁️
        </div>
        <h2 className="mt-4 text-lg font-extrabold text-ink">
          Données momentanément indisponibles
        </h2>
        <p className="mt-2 text-sm text-ink/55">{message}</p>
        <button onClick={onRetry} className="btn-primary mt-5">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
            <path d="M21 12a9 9 0 1 1-2.6-6.4M21 4v5h-5" />
          </svg>
          Réessayer
        </button>
      </div>
    </div>
  )
}