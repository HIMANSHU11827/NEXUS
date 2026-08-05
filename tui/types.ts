/**
 * Nexus TUI v3.0 — Shared Types
 * Centralized type definitions for the redesigned TUI.
 */
import type {ReactNode} from 'react';

export type Role = 'user' | 'assistant' | 'system' | 'command' | 'activity';

export interface Message {
    role: Role;
    content: string;
    id?: string;
    timestamp?: number;
}

export type ActivityKind =
    | 'tool' | 'command' | 'file' | 'test' | 'search' | 'browser'
    | 'mcp' | 'skill' | 'plugin' | 'hive' | 'agent' | 'worker' | 'provider'
    | 'rag' | 'approval' | 'error' | 'retry' | 'plan' | 'todo'
    | 'memory' | 'background' | 'compact' | 'config' | 'settings' | 'run' | 'terminal';

export type ActivityStatus = 'running' | 'done' | 'error' | 'pending' | 'cancelled' | string;

export interface ActivityItem {
    id: string;
    number: number;
    kind: ActivityKind;
    title: string;
    status: ActivityStatus;
    toolName?: string;
    summary?: string;
    command?: string;
    operation?: string;
    files?: string[];
    sources?: string[];
    output?: string;
    error?: string;
    durationMs?: number;
    startTime?: number;
    logo?: string;
    logoColor?: string;
    showInput?: boolean;
    showOutput?: boolean;
    showSources?: boolean;
    maxPreviewLines?: number;
    maxPreviewChars?: number;
    intent?: string;
    rules?: string[];
    conditions?: string[];
    oneTimeUse?: boolean;
    maxPerTask?: number;
    parallel?: boolean;
    maxParallel?: number;
    cooldownMs?: number;
}

export interface AgentInfo {
    id: string;
    name: string;
    status: string;
    agentId?: string;
    persona?: string;
    task?: string;
    activity?: string;
    durationMs?: number;
    toolsUsed?: number;
    messages?: number;
    errors?: string[];
    filesChanged?: string[];
    startTime?: number;
    startMs?: number;
    messagesSent?: number;
    completedAt?: string;
    retryCount?: number;
    finalResult?: string;
    cancelled?: boolean;
    history?: any[];
}

export interface TaskItem {
    id: string;
    subject: string;
    status: string;
}

export interface FileStatus {
    name: string;
    status: string;
}

export interface TimelineEntry {
    key: string;
    logo: string;
    color: string;
    count: number;
    label: string;
}

export interface PlanItem {
    step: number;
    description: string;
    status: string;
}

export interface UsageInfo {
    tokens?: number;
    cost?: number;
    calls?: number;
    contextWindow?: number;
    inputTokens?: number;
    outputTokens?: number;
    model?: string;
    provider?: string;
    budgetLimit?: number;
    budgetUsed?: number;
}

export type PanelMode =
    | 'workspace'
    | 'activity'
    | 'plan'
    | 'hive'
    | 'agent'
    | 'question'
    | 'mcp'
    | 'close';

export type SandboxTier = 'no_sandbox' | 'normal' | 'docker';
export type PermissionMode = 'auto' | 'all' | 'allowlist' | 'ask';

export interface PendingQuestion {
    question: string;
    options?: string[];
    customMode?: boolean;
}

export interface ChatLine {
    key: string;
    text: string;
    color: string;
    prefix?: string;
    prefixColor?: string;
    reservePrefix?: boolean;
    bold?: boolean;
    activityId?: string;
    msgRole?: Role;
}

// Theme types
export interface TuiTheme {
    // Base
    bg: string;
    panelBg: string;
    panelSoftBg: string;
    borderSoft: string;

    // Text
    text: string;
    textDim: string;
    textMuted: string;

    // Accent
    primary: string;
    secondary: string;
    success: string;
    warning: string;
    error: string;
    info: string;

    // Roles
    userColor: string;
    assistantColor: string;
    toolColor: string;
    hiveColor: string;
    planColor: string;
    mcpColor: string;
    skillColor: string;

    // Status
    statusRunning: string;
    statusDone: string;
    statusError: string;
    statusPending: string;
}
