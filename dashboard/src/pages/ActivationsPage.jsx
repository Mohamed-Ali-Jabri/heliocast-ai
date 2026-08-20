import { SITES, TOTAL_CAPACITY } from '../config/sites'
import { useActivations } from '../context/ActivationsContext'
import { fmtMw } from '../utils/format'

export default function ActivationsPage() {
  const { factors, setFactor, toggle, setAll, activeCapacity, activeSites } = useActivations()

  return (
    <div className="space-y-6">
      <section className="card relative overflow-hidden p-6 animate-fade-up">
        <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-gradient-to-br from-energy-400/25 to-transparent blur-2xl" />
        <div className="relative flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-extrabold text-ink">État des centrales</h1>
            <p className="text-sm font-medium text-ink/50">
              Activez, désactivez ou réduisez la capacité de chaque centrale — tous les calculs sont mis à jour en direct
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="chip bg-steg-50 text-steg-700">
              {fmtMw(activeCapacity)} / {TOTAL_CAPACITY} MWh actifs
            </span>
            <button onClick={() => setAll(100)} className="btn-ghost !px-3 !py-1.5 text-xs">
              Tout ON
            </button>
            <button onClick={() => setAll(0)} className="btn-ghost !px-3 !py-1.5 text-xs">
              Tout OFF
            </button>
          </div>
        </div>
      </section>

      <section className="card p-6 animate-fade-up" style={{ animationDelay: '80ms' }}>
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-extrabold text-ink">Réglage par centrale</h2>
            <p className="text-xs font-medium text-ink/50">
              {activeSites} / {SITES.length} centrales en service
            </p>
          </div>
        </div>
        <div className="space-y-3">
          {SITES.map((s) => {
            const factor = factors[s.id] ?? 100
            const active = s.capacity * (factor / 100)
            return (
              <div
                key={s.id}
                className={`flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3 transition-all duration-300 ${
                  factor > 0 ? 'bg-ink/3 ring-1 ring-ink/5' : 'bg-ink/2 ring-1 ring-ink/5 opacity-60'
                }`}
              >
                <div className="flex items-center gap-3">
                  <span className="h-3 w-3 rounded-full" style={{ backgroundColor: factor > 0 ? s.color : '#cbd5e1' }} />
                  <div>
                    <p className="text-sm font-semibold text-ink">
                      {s.name} <span className="text-[11px] font-medium text-ink/40">{s.city}</span>
                    </p>
                    <p className="text-[11px] font-medium text-ink/45">
                      {s.capacity} MWh → {fmtMw(active)} actifs
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-3">
                    <span className="w-14 text-right text-xs font-bold text-ink/60">{factor} %</span>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={factor}
                      onChange={(e) => setFactor(s.id, Number(e.target.value))}
                      aria-label={`Capacité ${s.name}`}
                      className="h-2 w-40 cursor-pointer appearance-none rounded-full bg-ink/10 accent-emerald-600"
                      title={`Capacité de ${s.name} : ${factor} %`}
                    />
                  </div>
                  <button
                    onClick={() => toggle(s.id)}
                    aria-label={factor > 0 ? 'Désactiver' : 'Activer'}
                    className={`relative h-6 w-11 rounded-full transition-colors duration-300 ${
                      factor > 0 ? 'bg-emerald-500' : 'bg-ink/20'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all duration-300 ${
                        factor > 0 ? 'left-[22px]' : 'left-0.5'
                      }`}
                    />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </div>
  )
}