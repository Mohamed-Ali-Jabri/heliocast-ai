import AnimatedNumber from './AnimatedNumber'

const ACCENTS = {
  blue: 'bg-steg-50 text-steg-700',
  orange: 'bg-energy-50 text-energy-600',
  green: 'bg-emerald-50 text-emerald-600',
  violet: 'bg-violet-50 text-violet-600',
}

export default function StatCard({ title, value, format, icon, accent = 'blue', sub, delay = 0 }) {
  return (
    <div
      className="card group p-5 animate-fade-up"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-ink/45">
            {title}
          </p>
          <p className="mt-2 text-2xl font-extrabold tracking-tight text-ink">
            <AnimatedNumber value={value} format={format} />
          </p>
          {sub && <p className="mt-1 text-xs font-medium text-ink/50">{sub}</p>}
        </div>
        <div
          className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl transition-transform duration-300 group-hover:scale-110 ${ACCENTS[accent]}`}
        >
          {icon}
        </div>
      </div>
    </div>
  )
}