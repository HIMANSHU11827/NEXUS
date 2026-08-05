import mascot from '../assets/nexus-mascot-brand.png'

export default function ThinkingAnimation() {
  return (
    <div className="relative flex h-6 w-6 items-center justify-center">
      {/* Outer glow ring */}
      <span className="absolute inset-0 rounded-full bg-primary/10 animate-pulse" style={{ animationDuration: '2.5s' }} />
      
      {/* Expanding ripple effect */}
      <span className="absolute inset-0 rounded-full border-2 border-primary/30 scale-50 animate-ping" style={{ animationDuration: '2s' }} />
      
      {/* Rotating dashed ring */}
      <span className="absolute inset-0 rounded-full border-2 border-dashed border-primary/40 animate-spin" style={{ animationDuration: '3s' }} />
      
      {/* Inner pulsing ring */}
      <span className="absolute inset-1 rounded-full border border-primary/50 animate-pulse" style={{ animationDuration: '1.5s' }} />
      
      {/* Mascot image with glow */}
      <img
        src={mascot}
        alt="Nexus thinking"
        className="relative z-10 h-4 w-4 object-contain animate-pulse"
        style={{ animationDuration: '1s', filter: 'drop-shadow(0 0 6px rgba(var(--primary),0.5))' }}
      />
    </div>
  )
}
