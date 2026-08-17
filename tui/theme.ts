/**
 * Nexus TUI v3.0 — Theme System
 * Dark/Light adaptive color scheme with 50+ color tokens.
 */
import type {TuiTheme} from './types.js';

/** NEXUS brand accents: cool blue for the core, warm orange for emphasis. */
export const NEXUS_BLUE = '#4da3ff';
export const NEXUS_BLUE_BRIGHT = '#72b7ff';
export const NEXUS_ORANGE = '#ff9f43';
export const NEXUS_ORANGE_BRIGHT = '#ffb454';

/** Shared filled transcript surface for user, assistant, and activity rows. */
export const TRANSCRIPT_SURFACE_BG = '#292929';

export const DARK_THEME: TuiTheme = {
    // Base
    bg: '',
    panelBg: '#15191f',
    panelSoftBg: '#11151b',
    borderSoft: '#374151',

    // Text
    text: '#e0e0e0',
    textDim: '#a3aab7',
    textMuted: '#7f8794',

    // Accent
    primary: NEXUS_BLUE,
    secondary: NEXUS_BLUE_BRIGHT,
    success: '#22c55e',
    warning: NEXUS_ORANGE,
    error: '#ef4444',
    info: '#3b82f6',

    // Roles
    userColor: NEXUS_BLUE,
    assistantColor: NEXUS_BLUE_BRIGHT,
    toolColor: NEXUS_BLUE,
    hiveColor: NEXUS_ORANGE_BRIGHT,
    planColor: NEXUS_ORANGE,
    mcpColor: NEXUS_ORANGE,
    skillColor: NEXUS_BLUE_BRIGHT,

    // Status
    statusRunning: '#3b82f6',
    statusDone: '#22c55e',
    statusError: '#ef4444',
    statusPending: '#666666',
};

export const LIGHT_THEME: TuiTheme = {
    bg: '',
    panelBg: '#f0f0f5',
    panelSoftBg: '#e8e8f0',
    borderSoft: '#d0d0e0',

    text: '#1a1a2e',
    textDim: '#666666',
    textMuted: '#999999',

    primary: '#2563eb',
    secondary: '#1d4ed8',
    success: '#16a34a',
    warning: '#ea7b12',
    error: '#dc2626',
    info: '#2563eb',

    userColor: '#2563eb',
    assistantColor: '#1d4ed8',
    toolColor: '#2563eb',
    hiveColor: '#c76b12',
    planColor: '#ea7b12',
    mcpColor: '#c76b12',
    skillColor: '#1d4ed8',

    statusRunning: '#2563eb',
    statusDone: '#16a34a',
    statusError: '#dc2626',
    statusPending: '#999999',
};

// Detect terminal background
let currentTheme: TuiTheme = DARK_THEME;

export function getTheme(): TuiTheme {
    return currentTheme;
}

export function setDarkMode(dark: boolean): void {
    currentTheme = dark ? DARK_THEME : LIGHT_THEME;
}

// Color utilities for activity kinds
export function activityColor(kind: string): string {
    const theme = getTheme();
    const map: Record<string, string> = {
        tool: theme.toolColor,
        command: theme.toolColor,
        file: theme.success,
        test: theme.info,
        search: theme.warning,
        browser: theme.secondary,
        mcp: theme.mcpColor,
        skill: theme.skillColor,
        plugin: theme.secondary,
        hive: theme.hiveColor,
        agent: theme.hiveColor,
        worker: theme.hiveColor,
        provider: theme.primary,
        rag: theme.info,
        approval: theme.warning,
        error: theme.error,
        retry: theme.warning,
        plan: theme.planColor,
        todo: theme.textDim,
        memory: theme.info,
        background: theme.textMuted,
    };
    return map[kind] || theme.textDim;
}

export function activityGlyph(kind: string): string {
    const map: Record<string, string> = {
        tool: '>',
        command: '$',
        terminal: '$',
        run: '$',
        file: '+',
        test: '#',
        search: '?',
        browser: '@',
        mcp: '&',
        skill: '*',
        plugin: '*',
        hive: 'H',
        agent: 'A',
        worker: 'A',
        provider: 'P',
        rag: 'R',
        approval: '!',
        error: '!',
        retry: '~',
        plan: '=',
        todo: '=',
        memory: 'M',
        compact: 'M',
        background: '~',
        config: '%',
        settings: '%',
    };
    return map[kind] || '>';
}

export function statusColor(status: string): string {
    const theme = getTheme();
    const s = status.toLowerCase();
    if (['active', 'running', 'working', 'busy', 'spawned', 'in_progress'].includes(s))
        return theme.statusRunning;
    if (['done', 'completed', 'success', 'finished'].includes(s))
        return theme.statusDone;
    if (['error', 'failed', 'cancelled'].includes(s))
        return theme.statusError;
    return theme.statusPending;
}

export function statusGlyph(status: string): string {
    const s = status.toLowerCase();
    if (['active', 'running', 'working', 'busy', 'spawned', 'in_progress'].includes(s)) return '●';
    if (['done', 'completed', 'success', 'finished'].includes(s)) return '✓';
    if (['error', 'failed'].includes(s)) return '✕';
    if (['cancelled'].includes(s)) return '⊘';
    if (['retrying'].includes(s)) return '↻';
    return '○';
}

export function taskStatusGlyph(status: string): string {
    const s = status.toLowerCase();
    if (['active', 'running', 'working', 'in_progress'].includes(s)) return '●';
    if (['done', 'completed', 'finished'].includes(s)) return '✓';
    if (['failed', 'error'].includes(s)) return '✕';
    if (['pending', 'queued'].includes(s)) return '○';
    if (['cancelled'].includes(s)) return '⊘';
    return '·';
}
