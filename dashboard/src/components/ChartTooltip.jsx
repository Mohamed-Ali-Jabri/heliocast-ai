const CARD = {
  backgroundColor: 'rgba(15,31,56,0.94)',
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: 14,
  padding: '10px 14px',
  fontSize: 12.5,
  color: '#e7eef9',
  boxShadow: '0 14px 34px -8px rgba(15,31,56,0.4)',
}

export default function ChartTooltip({ active, payload = [], label, unit = 'MW' }) {
  if (!active || !payload?.length) return null
  return (
    <div style={CARD}>
      {label !== undefined && label !== '' && (
        <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-steg-300">
          {label}
        </p>
      )}
      {payload.map((p) => (
        <p key={p.dataKey ?? p.name} className="flex items-center gap-2 text-sm font-semibold">
          <span
            className="inline-block h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: p.color || p.fill }}
          />
          {p.name ?? p.dataKey} :{' '}
          <span className="text-energy-400">
            {Number(p.value).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} {unit}
          </span>
        </p>
      ))}
    </div>
  )
}