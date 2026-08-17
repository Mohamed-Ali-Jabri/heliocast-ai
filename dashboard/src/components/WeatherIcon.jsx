export default function WeatherIcon({ kind = 'soleil', size = 28, animate = true }) {
  const spin = animate ? 'animate-spin-slow' : ''
  const pulse = animate ? 'animate-pulse-soft' : ''

  if (kind === 'soleil') {
    return (
      <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
        <g className={spin} style={{ transformOrigin: '32px 32px' }}>
          {Array.from({ length: 12 }).map((_, i) => {
            const a = (i * Math.PI) / 6
            return (
              <line
                key={i}
                x1={32 + 28 * Math.cos(a)}
                y1={32 + 28 * Math.sin(a)}
                x2={32 + 37 * Math.cos(a)}
                y2={32 + 37 * Math.sin(a)}
                stroke="#fb923c"
                strokeWidth="3.4"
                strokeLinecap="round"
              />
            )
          })}
        </g>
        <circle cx="32" cy="32" r="13" fill="#fbbf24" className={pulse} />
        <circle cx="27" cy="27" r="4" fill="#fef3c7" opacity="0.85" />
      </svg>
    )
  }

  if (kind === 'partiel') {
    return (
      <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
        <circle cx="24" cy="22" r="9" fill="#fbbf24" className={pulse} />
        <path
          d="M40 44c5.5 0 9.5-3.8 9.5-9a9 9 0 0 0-8.4-8.98A11 11 0 0 0 30.6 22 10.9 10.9 0 0 0 20.5 30.5c-3 .4-5.5 2.9-5.5 6a6.4 6.4 0 0 0 6.4 6.4H40v1z"
          fill="#cbd5e1"
        />
        <path d="M40 32a8 8 0 0 0-14.9-3.4" fill="#e2e8f0" />
      </svg>
    )
  }

  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden>
      <path
        d="M18 47c-6 0-10-4-10-9.5 0-5 3.6-8.8 8.4-9.4A14 14 0 0 1 30.6 18a14 14 0 0 1 13 8.6C51 27.5 56 33 56 40c0 7-5.6 12-12.6 12H18v-5z"
        fill="#cbd5e1"
      />
      <path d="M22 42c4 0 7-2.6 7-6.4 0-3-2.2-5.4-5.1-5.8" stroke="#94a3b8" strokeWidth="2.6" strokeLinecap="round" />
      <circle cx="40" cy="29" r="2.4" fill="#94a3b8" className={pulse} />
    </svg>
  )
}