export const colors = {
  bg: '#09090b',
  sidebar: '#18181b',
  cardHover: '#27272a',
  accent: {
    blue: '#3b82f6',
    cyan: '#06b6d4',
    indigo: '#4f46e5',
    green: '#22c55e',
    amber: '#f59e0b',
    red: '#ef4444',
    purple: '#a855f7',
    pink: '#ec4899',
  },
  text: {
    main: '#fafafa',
    muted: '#a1a1aa',
    dim: '#71717a',
  },
  border: {
    dim: '#27272a',
    focus: '#3f3f46',
  },
  bubble: {
    assistant: {
      bg: 'rgba(255, 255, 255, 0.02)',
      border: 'rgba(255, 255, 255, 0.06)',
      text: '#f3f4f6',
    },
    user: {
      bg: 'rgba(59, 130, 246, 0.15)',
      border: 'rgba(59, 130, 246, 0.22)',
      text: '#f3f4f6',
    },
  },
  avatar: {
    user: { bg: 'rgba(59, 130, 246, 0.10)', border: 'rgba(59, 130, 246, 0.22)' },
    assistant: { bg: 'rgba(16, 185, 129, 0.10)', border: 'rgba(16, 185, 129, 0.22)' },
  },
  work: {
    bg: 'rgba(15, 23, 42, 0.78)',
    bgHover: 'rgba(30, 41, 59, 0.86)',
    planBg: 'rgba(20, 36, 61, 0.86)',
    border: 'rgba(148, 163, 184, 0.20)',
    borderHover: 'rgba(96, 165, 250, 0.44)',
    text: '#f8fafc',
    muted: '#cbd5e1',
    codeBg: 'rgba(2, 6, 23, 0.72)',
    codeText: '#bfdbfe',
    codeBorder: 'rgba(96, 165, 250, 0.24)',
    iconBg: 'rgba(96, 165, 250, 0.12)',
    iconBorder: 'rgba(96, 165, 250, 0.26)',
    iconText: '#bfdbfe',
  },
  card: {
    planning: { bg: 'rgba(59, 130, 246, 0.08)', border: 'rgba(59, 130, 246, 0.25)', icon: '#3b82f6' },
    tool: { bg: 'rgba(168, 85, 247, 0.08)', border: 'rgba(168, 85, 247, 0.25)', icon: '#a855f7' },
    command: { bg: 'rgba(34, 197, 94, 0.08)', border: 'rgba(34, 197, 94, 0.25)', icon: '#22c55e' },
    file: { bg: 'rgba(6, 182, 212, 0.08)', border: 'rgba(6, 182, 212, 0.25)', icon: '#06b6d4' },
    error: { bg: 'rgba(239, 68, 68, 0.08)', border: 'rgba(239, 68, 68, 0.25)', icon: '#ef4444' },
    agent: { bg: 'rgba(245, 158, 11, 0.08)', border: 'rgba(245, 158, 11, 0.25)', icon: '#f59e0b' },
    search: { bg: 'rgba(236, 72, 153, 0.08)', border: 'rgba(236, 72, 153, 0.25)', icon: '#ec4899' },
    mcp: { bg: 'rgba(99, 102, 241, 0.08)', border: 'rgba(99, 102, 241, 0.25)', icon: '#6366f1' },
  },
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  '2xl': 32,
  '3xl': 48,
  '4xl': 64,
} as const;

export const typography = {
  fontFamily: "'Outfit', -apple-system, system-ui, sans-serif",
  fontMono: "'JetBrains Mono', 'Fira Code', monospace",
  sizes: {
    xs: '0.75rem',
    sm: '0.875rem',
    base: '1rem',
    lg: '1.125rem',
    xl: '1.25rem',
    '2xl': '1.5rem',
    '3xl': '1.875rem',
    '4xl': '2.25rem',
  },
  weights: {
    light: 300,
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
    extrabold: 800,
    black: 900,
  },
} as const;

export const shadows = {
  sm: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
  md: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
  lg: '0 10px 15px -3px rgb(0 0 0 / 0.1)',
  xl: '0 20px 25px -5px rgb(0 0 0 / 0.1)',
  glow: {
    blue: '0 0 20px rgba(59, 130, 246, 0.15)',
    purple: '0 0 20px rgba(168, 85, 247, 0.15)',
    green: '0 0 20px rgba(34, 197, 94, 0.15)',
    cyan: '0 0 20px rgba(6, 182, 212, 0.15)',
  },
} as const;

export const radii = {
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  full: 9999,
} as const;

export const breakpoints = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
} as const;

export const animations = {
  fast: '150ms',
  normal: '250ms',
  slow: '350ms',
  spring: 'cubic-bezier(0.16, 1, 0.3, 1)',
} as const;

export const panels = {
  sidebar: {
    defaultWidth: 250,
    minWidth: 210,
    maxWidth: 420,
  },
  drawer: {
    defaultWidth: 390,
    minWidth: 320,
    maxWidth: '62vw' as const,
  },
  canvas: {
    defaultWidth: 768,
    minWidth: 460,
    maxWidth: '78vw' as const,
  },
} as const;

export const nexusTheme = {
  colors,
  spacing,
  typography,
  shadows,
  radii,
  breakpoints,
  animations,
  panels,
} as const;

export type NexusTheme = typeof nexusTheme;
