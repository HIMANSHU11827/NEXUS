/**
 * Nexus TUI v3.0 — Theme System
 * Dark/Light adaptive color scheme with 50+ color tokens.
 */
import type {TuiTheme} from './types.js';

export const DARK_THEME: TuiTheme = {
    // Base
    bg: '',
    panelBg: '#1a1a2e',
    panelSoftBg: '#16213e',
    borderSoft: '#2a2a4a',

    // Text
    text: '#e0e0e0',
    textDim: '#888888',
    textMuted: '#666666',

    // Accent
    primary: '#7c3aed',
    secondary: '#06b6d4',
    success: '#22c55e',
    warning: '#f59e0b',
    error: '#ef4444',
    info: '#3b82f6',

    // Roles
    userColor: '#3b82f6',
    assistantColor: '#a78bfa',
    toolColor: '#6366f1',
    hiveColor: '#8b5cf6',
    planColor: '#f59e0b',
    mcpColor: '#ec4899',
    skillColor: '#10b981',

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

    primary: '#7c3aed',
    secondary: '#0891b2',
    success: '#16a34a',
    warning: '#d97706',
    error: '#dc2626',
    info: '#2563eb',

    userColor: '#2563eb',
    assistantColor: '#7c3aed',
    toolColor: '#4f46e5',
    hiveColor: '#6d28d9',
    planColor: '#d97706',
    mcpColor: '#db2777',
    skillColor: '#059669',

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
        tool: '🔧',
        command: '⚡',
        file: '📄',
        test: '🧪',
        search: '🔍',
        browser: '🌐',
        mcp: '🔌',
        skill: '🎯',
        plugin: '🧩',
        hive: '🐝',
        agent: '🤖',
        worker: '👷',
        provider: '☁️',
        rag: '📚',
        approval: '✋',
        error: '❌',
        retry: '🔄',
        plan: '📋',
        todo: '✅',
        memory: '🧠',
        background: '⏳',
    };
    return map[kind] || '•';
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
