export default function SecondLogoAnimation() {
  return (
    <div className="relative flex h-6 w-6 items-center justify-center">
      {/* Outer glow */}
      <span className="absolute inset-0 rounded-full bg-primary/10 animate-pulse" style={{ animationDuration: '2s' }} />
      
      {/* Expanding ripple */}
      <span className="absolute inset-0 rounded-full border border-primary/30 scale-50 animate-ping" style={{ animationDuration: '2.5s' }} />
      
      {/* Knot shape using SVG */}
      <svg
        viewBox="0 0 24 24"
        fill="none"
        className="relative z-10 h-5 w-5 animate-pulse"
        style={{ animationDuration: '1.5s', filter: 'drop-shadow(0 0 4px rgba(var(--primary),0.4))' }}
      >
        {/* Main knot path - infinity-like shape */}
        <path
          d="M12 4C8.5 4 6 6.5 6 9C6 11.5 8 13 10 14C8 15 6 16.5 6 19C6 21.5 8.5 24 12 24C15.5 24 18 21.5 18 19C18 16.5 16 15 14 14C16 13 18 11.5 18 9C18 6.5 15.5 4 12 4Z"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          className="text-primary animate-spin"
          style={{ animationDuration: '3s' }}
        />
        
        {/* Inner knot detail */}
        <path
          d="M12 7C10 7 9 8 9 9C9 10 10 11 12 11C14 11 15 10 15 9C15 8 14 7 12 7Z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          className="text-primary/60"
        />
        
        {/* Small face elements */}
        <circle cx="10" cy="12" r="1" fill="currentColor" className="text-primary" />
        <circle cx="14" cy="12" r="1" fill="currentColor" className="text-primary" />
        <path
          d="M11 14Q12 15 13 14"
          stroke="currentColor"
          strokeWidth="1"
          strokeLinecap="round"
          className="text-primary/70"
        />
      </svg>
      
      {/* Rotating ring around knot */}
      <span className="absolute inset-0 rounded-full border-2 border-dashed border-primary/20 animate-spin" style={{ animationDuration: '4s' }} />
      
      {/* Inner pulsing core */}
      <span className="absolute inset-2 rounded-full bg-primary/20 animate-pulse" style={{ animationDuration: '1s' }} />
    </div>
  )
}
