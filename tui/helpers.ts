/**
 * Nexus TUI v3.0 — Shared Helpers
 * Pure functions, constants and types extracted from the nexus-tui.tsx monolith.
 * No React state lives here; components and the app orchestrator import these.
 */
import {existsSync, readFileSync} from 'node:fs';
import {mkdir, readFile, readdir, stat, writeFile} from 'node:fs/promises';
import {execFileSync, spawn, execFile as _execFile} from 'node:child_process';
import {randomBytes} from 'node:crypto';
import {promisify} from 'node:util';
import path from 'node:path';
import {NEXUS_BLUE, NEXUS_BLUE_BRIGHT, NEXUS_ORANGE, NEXUS_ORANGE_BRIGHT} from './theme.js';

// ── [NEXUS CONFIG]
const configuredApi = process.env.NEXUS_API?.trim();
const configuredHost = process.env.NEXUS_API_HOST?.trim() || '127.0.0.1';
const configuredPort = process.env.NEXUS_API_PORT?.trim() || '8000';
export const API_BASE = configuredApi
    ? configuredApi.replace(/\/$/, '')
    : `http://${configuredHost}:${configuredPort}/api`;
// The repository launcher injects a token, but direct `npm start` usage does
// not. Generate a per-process local token so the embedded server and TUI use
// the same authenticated contract without falling back to a shared constant.
export const DASHBOARD_TOKEN = process.env.NEXUS_DASHBOARD_TOKEN?.trim() || randomBytes(32).toString('hex');
export const API_AUTH_HEADERS: Record<string, string> = {
    Authorization: `Bearer ${DASHBOARD_TOKEN}`
};
export const API_JSON_HEADERS: Record<string, string> = {
    ...API_AUTH_HEADERS,
    'Content-Type': 'application/json'
};
export type SandboxTier = 'no_sandbox' | 'normal' | 'docker';
export type PermissionMode = 'auto' | 'all' | 'allowlist' | 'ask';

export const normalizeSandboxTier = (value: string): SandboxTier => {
    const normalized = String(value || '').trim().toLowerCase().replace(/\s+/g, '_');
    if (['normal', 'simple', 'on', 'safe'].includes(normalized)) return 'normal';
    if (['docker', 'advanced'].includes(normalized)) return 'docker';
    return 'no_sandbox';
};

export const nextSandboxTier = (tier: SandboxTier): SandboxTier => {
    if (tier === 'no_sandbox') return 'normal';
    if (tier === 'normal') return 'docker';
    return 'no_sandbox';
};

export const sandboxLabel = (tier: SandboxTier) => {
    if (tier === 'normal') return 'sandbox: simple';
    if (tier === 'docker') return 'sandbox: advanced';
    return 'sandbox: none';
};

export const normalizePermissionMode = (value: string): PermissionMode => {
    const normalized = String(value || '').trim().toLowerCase().replace(/[\s-]+/g, '_');
    if (['all', 'bypass', 'dontask', 'dont_ask', 'noask'].includes(normalized)) return 'all';
    if (['allowlist', 'allow_list', 'whitelist', 'pre_authorized', 'checklist'].includes(normalized)) return 'allowlist';
    if (['ask', 'approve', 'approval', 'default', 'ask_once', 'once'].includes(normalized)) return 'ask';
    return 'auto';
};

export const nextPermissionMode = (mode: PermissionMode): PermissionMode => {
    if (mode === 'auto') return 'all';
    if (mode === 'all') return 'allowlist';
    if (mode === 'allowlist') return 'ask';
    return 'auto';
};

export const permissionLabel = (mode: PermissionMode) => `perm: ${mode}`;
export const PROJECT_ROOT = existsSync(path.resolve(process.cwd(), 'pyproject.toml'))
    ? process.cwd()
    : path.resolve(process.cwd(), '..');
const venvPython = process.platform === 'win32'
    ? path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe')
    : path.join(PROJECT_ROOT, '.venv', 'bin', 'python');
export const PYTHON_EXECUTABLE = existsSync(venvPython) ? venvPython : 'python';
export const execFileAsync = promisify(_execFile);

export const syncStopVoiceProcess = () => {
    try {
        execFileSync('powershell.exe', [
            '-NoProfile',
            '-Command',
            `$ProgressPreference='SilentlyContinue'; try { Invoke-RestMethod -Method Post -Uri '${API_BASE}/voice/stop' | Out-Null } catch { }`
        ], {
            cwd: PROJECT_ROOT,
            stdio: 'ignore',
            timeout: 2500,
            windowsHide: true
        });
    } catch {
        // Best effort shutdown.
    }
};

export interface Message {
    role: string;
    content: string;
    activityId?: string;
    progress?: ProgressSummary;
}

/**
 * Public execution telemetry rendered between tool rows.  This is deliberately
 * smaller than a canonical event: provider messages, model reasoning, raw
 * arguments, and arbitrary payload fields never cross this projection.
 */
export interface ProgressSummary {
    id: string;
    currentAction: string;
    evidence?: string;
    retryReason?: string;
    nextAction?: string;
    phase?: string;
    tool?: string;
    outcome?: string;
    planId?: string;
    stepId?: string;
    stepIndex?: number;
}

const visibleProgressText = (value: unknown, maxLength = 320): string => {
    const withoutPrivateBlocks = String(value ?? '')
        .replace(/<think\b[^>]*>[\s\S]*?(?:<\/think>|$)/gi, ' ')
        .replace(/<reasoning\b[^>]*>[\s\S]*?(?:<\/reasoning>|$)/gi, ' ')
        .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
        .replace(/[\u0000-\u001f\u007f]/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
    if (!withoutPrivateBlocks) return '';
    if (/^(?:chain[- ]of[- ]thought|reasoning|hidden thought|internal thought|thought|analysis)\s*:/i.test(withoutPrivateBlocks)) {
        return '';
    }
    return withoutPrivateBlocks.slice(0, Math.max(1, maxLength));
};

const progressPayload = (event: Record<string, any>): Record<string, any> =>
    event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
        ? event.payload
        : {};

/** Project one deterministic public assistant.progress event into safe UI text. */
export const progressSummaryFromWorkEvent = (input: Record<string, any>): ProgressSummary | null => {
    if (!input || typeof input !== 'object') return null;
    const eventType = String(input.event_type || input.type || '').toLowerCase();
    if (eventType !== 'assistant.progress') return null;
    if (input.visibility && String(input.visibility).toLowerCase() !== 'public') return null;

    const payload = progressPayload(input);
    if (payload.projection !== 'deterministic-v1') return null;
    const currentAction = visibleProgressText(payload.current_action);
    if (!currentAction) return null;

    const id = visibleProgressText(
        input.event_id || input.id || `progress-${input.sequence || currentAction}`,
        180
    );
    const evidence = visibleProgressText(payload.evidence, 360);
    const retryReason = visibleProgressText(payload.retry_reason, 280);
    const nextAction = visibleProgressText(payload.next_action, 160);
    const phase = visibleProgressText(payload.phase, 80);
    const tool = visibleProgressText(payload.tool, 120);
    const outcome = visibleProgressText(payload.outcome, 80);
    const planId = visibleProgressText(payload.plan_id, 120);
    const stepId = visibleProgressText(payload.step_id, 160);
    const rawStepIndex = Number(payload.step_index);
    const stepIndex = Number.isFinite(rawStepIndex) && rawStepIndex >= 0
        ? (rawStepIndex === 0 ? 1 : rawStepIndex)
        : undefined;

    return {
        id: id || `progress-${String(input.sequence || 'event')}`,
        currentAction,
        ...(evidence ? {evidence} : {}),
        ...(retryReason ? {retryReason} : {}),
        ...(nextAction ? {nextAction} : {}),
        ...(phase ? {phase} : {}),
        ...(tool ? {tool} : {}),
        ...(outcome ? {outcome} : {}),
        ...(planId ? {planId} : {}),
        ...(stepId ? {stepId} : {}),
        ...(stepIndex !== undefined ? {stepIndex} : {})
    };
};

const humanizeProgressCode = (value: string): string => value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

/** One concise transcript sentence built only from the safe projection. */
export const progressSummaryText = (progress: ProgressSummary): string => {
    const parts = [progress.currentAction];
    if (progress.evidence) parts.push(`evidence: ${progress.evidence}`);
    if (progress.retryReason) parts.push(`retry: ${progress.retryReason}`);
    if (progress.nextAction) parts.push(`next: ${humanizeProgressCode(progress.nextAction)}`);
    return parts.filter(Boolean).join(' · ');
};

export interface FileStatus {
    name: string;
    status: string;
    additions?: number;
    deletions?: number;
}

const optionalFileCount = (value: unknown): number | undefined => {
    const count = Number(value);
    return Number.isFinite(count) && count >= 0 ? count : undefined;
};

/** Project only real file mutations into the sidebar's CHANGES list. */
export const fileStatusFromWorkEvent = (input: Record<string, any>): FileStatus | null => {
    const event = adaptCanonicalEvent(input);
    const kind = String(event.kind || event.type || '').toLowerCase();
    const eventType = String(event.event_type || event.type || '').toLowerCase();
    const action = String(event.operation || event.action || event.title || event.tool || '').toLowerCase();
    const isFile = kind === 'file' || eventType.startsWith('file.') || Boolean(event.path || event.file || event.file_path);
    const isRead = eventType === 'file.read' || /\b(read|view|open|inspect)\b/.test(action);
    const isMutation = eventType === 'file.created'
        || eventType === 'file.edited'
        || eventType === 'file.diff'
        || /\b(create|created|write|written|edit|edited|modify|modified|update|updated|delete|deleted|remove|removed)\b/.test(action);
    if (!isFile || isRead || !isMutation) return null;

    const target = String(
        event.target
        || event.path
        || event.file
        || event.file_path
        || event.related_files?.[0]
        || event.payload?.target
        || event.payload?.path
        || ''
    ).trim();
    if (!target) return null;

    const changes = event.changed_lines || event.line_changes || event.payload?.changed_lines || event.payload?.line_changes;
    const additions = optionalFileCount(
        typeof changes === 'object' && changes !== null
            ? changes.added ?? changes.additions ?? changes.inserted
            : event.additions ?? event.insertions
    );
    const deletions = optionalFileCount(
        typeof changes === 'object' && changes !== null
            ? changes.removed ?? changes.deleted ?? changes.deletions
            : event.deletions ?? event.removals
    );
    return {
        name: target,
        status: String(event.operation || event.action || eventType || 'modified').toUpperCase(),
        ...(additions !== undefined ? {additions} : {}),
        ...(deletions !== undefined ? {deletions} : {})
    };
};

export type TimelineKind = 'read' | 'write' | 'tool' | 'success' | 'error' | 'text' | 'step';

export interface TimelineEvent {
    kind: TimelineKind;
    weight: number;
    label: string;
}

export interface UsageStats {
    contextTokens: number;
    contextLimit: number;
    inputTokens: number;
    outputTokens: number;
    source: 'provider' | 'unavailable';
}

export interface AgentInfo {
    id: string;
    name: string;
    status: string;
    description?: string;
}

export interface TaskItem {
    id: string;
    subject: string;
    status: string;
    agent?: string;
    /** Local wall-clock time when the task was first observed (real runtime timing). */
    startedAt?: number;
}

export interface PlanChecklistItem {
    id: string;
    index: number;
    description: string;
    status: string;
    planId?: string;
    evidence?: string;
    retryReason?: string;
    nextAction?: string;
}

export const normalizePlanChecklistStatus = (value: unknown): string => {
    const status = String(value ?? '').trim().toLowerCase();
    if (['success', 'succeeded', 'done', 'completed', 'complete', 'applied'].includes(status)) return 'done';
    if (['failed', 'failure', 'error'].includes(status)) return 'failed';
    if (['blocked', 'waiting', 'paused', 'denied', 'rejected'].includes(status)) return 'blocked';
    if (['running', 'in_progress', 'working', 'active', 'started', 'approved'].includes(status)) return 'running';
    if (['cancelled', 'canceled', 'skipped'].includes(status)) return status === 'canceled' ? 'cancelled' : status;
    return 'pending';
};

const planItemKey = (value: unknown): string => String(value ?? '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();

const planStepDescription = (item: unknown): string => {
    if (typeof item === 'string') return visibleProgressText(item, 300);
    if (!item || typeof item !== 'object') return '';
    const value = item as Record<string, unknown>;
    return visibleProgressText(value.description ?? value.step ?? value.label ?? value.title, 300);
};

const planStepStatus = (item: unknown): string => {
    if (!item || typeof item !== 'object') return 'pending';
    const value = item as Record<string, unknown>;
    return normalizePlanChecklistStatus(value.status ?? value.state);
};

/**
 * Merge a canonical plan lifecycle event without discarding previously known
 * step identity/status. Full step lists define order; targeted updates modify
 * only their addressed step.
 */
export const mergePlanChecklistEvent = (
    previous: PlanChecklistItem[],
    input: Record<string, any>
): PlanChecklistItem[] => {
    const event = adaptCanonicalEvent(input);
    const eventType = String(event.event_type || event.type || '').toLowerCase();
    const eventKind = String(event.kind || '').toLowerCase();
    if (eventKind !== 'plan' && !eventType.startsWith('plan.')) return previous;

    const payload = progressPayload(event);
    const planId = visibleProgressText(event.plan_id ?? payload.plan_id, 120);
    const rawSteps = [event.items, event.steps, payload.items, payload.steps]
        .find(Array.isArray) as unknown[] | undefined;
    const priorById = new Map(previous.map(item => [item.id, item]));
    const priorByText = new Map(previous.map(item => [planItemKey(item.description), item]));
    let next = previous.map(item => ({...item}));

    if (rawSteps?.length) {
        next = rawSteps.map((raw, offset) => {
            const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
            const description = planStepDescription(raw);
            const rawIndex = Number(value.index ?? value.step_index ?? offset + 1);
            const index = Number.isFinite(rawIndex) && rawIndex > 0 ? rawIndex : offset + 1;
            const rawId = visibleProgressText(value.step_id ?? value.id, 160);
            const fallbackId = `${planId || event.run_id || event.turn_id || 'plan'}-step-${index}`;
            const existing = (rawId && priorById.get(rawId)) || priorByText.get(planItemKey(description));
            const explicitStatus = value.status != null || value.state != null;
            return {
                id: rawId || existing?.id || fallbackId,
                index,
                description: description || existing?.description || `Step ${index}`,
                status: explicitStatus ? planStepStatus(raw) : existing?.status || normalizePlanChecklistStatus(event.status),
                ...(planId || existing?.planId ? {planId: planId || existing?.planId} : {}),
                ...(existing?.evidence ? {evidence: existing.evidence} : {}),
                ...(existing?.retryReason ? {retryReason: existing.retryReason} : {}),
                ...(existing?.nextAction ? {nextAction: existing.nextAction} : {})
            };
        });
    }

    const rawStepIndex = Number(event.step_index ?? payload.step_index);
    const targetedIndex = Number.isFinite(rawStepIndex)
        ? (rawStepIndex === 0 ? 1 : rawStepIndex)
        : 0;
    const targetedId = visibleProgressText(event.step_id ?? payload.step_id, 160);
    const description = visibleProgressText(event.description ?? payload.description, 300);
    const isStepLifecycle = eventType.startsWith('plan.step.');
    if (targetedIndex || targetedId || (description && isStepLifecycle)) {
        const matchIndex = next.findIndex(item =>
            (targetedId && item.id === targetedId)
            || (targetedIndex > 0 && item.index === targetedIndex)
            || (description && planItemKey(item.description) === planItemKey(description))
        );
        const update = (item: PlanChecklistItem): PlanChecklistItem => ({
            ...item,
            status: normalizePlanChecklistStatus(event.status),
            ...(description ? {description} : {}),
            ...(planId ? {planId} : {})
        });
        if (matchIndex >= 0) {
            next[matchIndex] = update(next[matchIndex]);
        } else {
            const index = targetedIndex || next.length + 1;
            next.push(update({
                id: targetedId || `${planId || event.run_id || 'plan'}-step-${index}`,
                index,
                description: description || `Step ${index}`,
                status: 'pending'
            }));
        }
    }

    if (!targetedIndex && !targetedId && !isStepLifecycle) {
        const planStatus = normalizePlanChecklistStatus(event.status);
        if (planStatus === 'done') next = finalizePlanChecklist(next, 'done');
        if (planStatus === 'failed') next = finalizePlanChecklist(next, 'failed');
    }

    return next.sort((left, right) => left.index - right.index);
};

/** Overlay the session's durable WorkItems while preserving plan-event order. */
export const mergePlanChecklistTasks = (
    previous: PlanChecklistItem[],
    tasks: TaskItem[],
    appendUnmatched = true
): PlanChecklistItem[] => {
    if (!Array.isArray(tasks) || tasks.length === 0) return previous;
    const orderedTasks = [...tasks].sort((left, right) =>
        (left.startedAt || 0) - (right.startedAt || 0)
    );
    const taskById = new Map(orderedTasks.map(task => [task.id, task]));
    const taskByText = new Map(orderedTasks.map(task => [planItemKey(task.subject), task]));
    const consumed = new Set<string>();
    const merged = previous.map(item => {
        const task = taskById.get(item.id) || taskByText.get(planItemKey(item.description));
        if (!task) return item;
        consumed.add(task.id);
        return {...item, id: task.id, description: task.subject || item.description, status: normalizePlanChecklistStatus(task.status)};
    });
    if (!appendUnmatched) return merged;
    for (const task of orderedTasks) {
        if (consumed.has(task.id)) continue;
        merged.push({
            id: task.id,
            index: merged.length + 1,
            description: task.subject,
            status: normalizePlanChecklistStatus(task.status)
        });
    }
    return merged;
};

/** Attach safe progress evidence to a known plan step when identity is present. */
export const mergeProgressIntoPlanChecklist = (
    previous: PlanChecklistItem[],
    progress: ProgressSummary
): PlanChecklistItem[] => {
    if (!progress.stepId && !progress.stepIndex) return previous;
    const index = previous.findIndex(item =>
        (progress.stepId && item.id === progress.stepId)
        || (progress.stepIndex && item.index === progress.stepIndex)
    );
    if (index < 0) return previous;
    const outcome = normalizePlanChecklistStatus(progress.outcome);
    const next = [...previous];
    next[index] = {
        ...next[index],
        ...(progress.planId ? {planId: progress.planId} : {}),
        ...(progress.evidence ? {evidence: progress.evidence} : {}),
        ...(progress.retryReason ? {retryReason: progress.retryReason} : {}),
        ...(progress.nextAction ? {nextAction: progress.nextAction} : {}),
        ...(['done', 'failed', 'blocked', 'running'].includes(outcome) ? {status: outcome} : {})
    };
    return next;
};

export const finalizePlanChecklist = (
    items: PlanChecklistItem[],
    terminal: 'done' | 'failed' | 'cancelled'
): PlanChecklistItem[] => items.map(item => {
    if (['done', 'failed', 'cancelled', 'skipped'].includes(item.status)) return item;
    if (terminal === 'done') return {...item, status: 'done'};
    if (item.status === 'running') return {...item, status: terminal};
    return item;
});

export const planChecklistStatus = (items: PlanChecklistItem[], fallback = 'planning'): string => {
    if (items.length === 0) return fallback;
    if (items.some(item => item.status === 'running')) return 'running';
    if (items.some(item => item.status === 'failed')) return 'failed';
    if (items.every(item => ['done', 'skipped'].includes(item.status))) return 'done';
    if (items.some(item => item.status === 'blocked')) return 'blocked';
    return 'planning';
};

export interface QueueSnapshotTask {
    id: number;
    state: string;
    summary: string;
    session_id?: string;
    attempts?: number;
    max_attempts?: number;
}

/** Format the bounded server queue snapshot for the interactive command log. */
export const queueSnapshotLines = (value: unknown): string[] => {
    if (!value || typeof value !== 'object') return ['Queue status unavailable.'];
    const snapshot = value as Record<string, any>;
    const states = snapshot.states && typeof snapshot.states === 'object' ? snapshot.states : {};
    const stateLine = Object.entries(states)
        .map(([state, count]) => `${state}: ${Number(count) || 0}`)
        .join(' · ');
    const scope = String(snapshot.scope || 'project');
    const lines = [
        `queue (${scope}): ${Number(snapshot.pending) || 0} pending · mode: ${String(snapshot.mode || 'unknown')} · worker: ${String(snapshot.worker || 'unknown')}`,
        stateLine ? `states: ${stateLine}` : 'states: unavailable'
    ];
    const tasks = Array.isArray(snapshot.tasks) ? snapshot.tasks : [];
    if (tasks.length === 0) {
        lines.push('unfinished: none');
        return lines;
    }
    lines.push('unfinished:');
    for (const task of tasks.slice(0, 20)) {
        if (!task || typeof task !== 'object') continue;
        const id = String(task.id ?? '?');
        const state = String(task.state || 'unknown');
        const summary = String(task.summary || 'Task').replace(/\s+/g, ' ').trim();
        const attempts = task.attempts != null && task.max_attempts != null
            ? ` · ${task.attempts}/${task.max_attempts}`
            : '';
        lines.push(`  #${id} ${state}${attempts} · ${summary || 'Task'}`);
    }
    return lines;
};

/**
 * Keep internal checklist/status identifiers out of user-facing task rows.
 * The backend task id remains available on TaskItem.id for actions and
 * reconciliation; only accidental serialization prefixes are hidden.
 */
export const cleanTaskSubject = (value: unknown): string => {
    let subject = String(value ?? '').trim();
    subject = subject.replace(
        /^\[?(?:pending|queued|running|completed|failed|blocked|cancelled|skipped)(?:[_-]?[a-f0-9]{8,})\]\s*/i,
        ''
    );
    subject = subject.replace(/^\[(?:task[_-])?[a-f0-9]{8,}\]\s*/i, '');
    return subject.trim();
};

const taskStatusForTui = (value: unknown): string => {
    const status = String(value ?? '').trim().toLowerCase();
    if (['running', 'waiting', 'ready_for_review'].includes(status)) return 'running';
    if (['applied', 'completed', 'succeeded', 'success', 'done'].includes(status)) return 'completed';
    if (['failed', 'error'].includes(status)) return 'failed';
    if (['cancelled', 'canceled'].includes(status)) return 'cancelled';
    return 'pending';
};

/** Convert canonical session work items into the compact TUI task shape. */
export const taskItemsFromWorkItems = (value: unknown): TaskItem[] => {
    if (!Array.isArray(value)) return [];
    return value
        .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
        .map(item => ({
            id: String(item.task_id || item.id || '').trim(),
            subject: cleanTaskSubject(item.title || item.subject || 'Task'),
            status: taskStatusForTui(item.status),
            startedAt: typeof item.created_at === 'number' ? item.created_at * 1000 : undefined
        }))
        .filter(task => Boolean(task.id));
};

export type ActivityKind =
    | 'tool' | 'command' | 'file' | 'test' | 'search' | 'browser'
    | 'mcp' | 'skill' | 'plugin' | 'hive' | 'agent' | 'worker' | 'provider'
    | 'rag' | 'approval' | 'error' | 'retry' | 'plan' | 'todo'
    | 'memory' | 'background' | 'compact' | 'config' | 'settings' | 'run' | 'terminal';

export const PUBLIC_ACTIVITY_KINDS = new Set([
    'plan', 'todo', 'tool', 'command', 'file', 'test', 'search', 'browser',
    'mcp', 'skill', 'plugin', 'hive', 'agent', 'worker', 'provider', 'rag',
    'approval', 'guardrail', 'error', 'retry', 'completion', 'config', 'settings', 'compact'
]);
export const CHAT_ACTIVITY_KINDS = new Set<ActivityKind>([
    'tool', 'command', 'file', 'test', 'search', 'browser', 'mcp', 'skill',
    'plugin', 'hive', 'agent', 'worker', 'provider', 'rag', 'approval',
    'error', 'retry', 'plan', 'todo', 'memory', 'background', 'compact',
    'config', 'settings', 'run', 'terminal'
]);

export const adaptCanonicalEvent = (input: Record<string, any>): Record<string, any> => {
    const payload = input.payload && typeof input.payload === 'object' ? input.payload : {};
    const eventType = String(input.event_type || input.type || '').toLowerCase();
    const inputKind = String(input.kind || '').toLowerCase();
    const family = eventType.includes('.') ? eventType.split('.')[0] : '';
    const kind = family === 'web' ? 'search'
        : ['subagent', 'handoff'].includes(family) ? 'hive'
        : family === 'guardrail' ? 'approval'
        : family === 'completion' ? 'run'
        : ['plan', 'phase'].includes(family) ? 'plan'
        : ['run', 'conversation', 'message', 'status'].includes(family) ? 'agent'
        : family;
    const error = input.error && typeof input.error === 'object' ? input.error.message : input.error;
    return {
        ...payload, ...input,
        id: input.event_id || input.id,
        kind: ['subagent', 'handoff'].includes(inputKind) ? 'hive' : input.kind || kind || input.legacy_type || input.type,
        action: input.action || input.title || payload.action,
        target: input.target || payload.target || input.related_command || input.related_files?.[0] || input.related_tool,
        command: input.command || payload.command || input.related_command,
        tool: input.tool || payload.tool || input.related_tool,
        error: error || payload.error
    };
};

export interface ActivityItem {
    id: string;
    number: number;
    kind: ActivityKind;
    title: string;
    summary: string;
    status: string;
    detail?: string;
    output?: string;
    error?: string;
    files?: string[];
    command?: string;
    operation?: string;
    preview?: string;
    toolName?: string;
    logo?: string;
    logoColor?: string;
    startedAt?: number;
    durationMs?: number;
    sources?: string[];
    showSources?: boolean;
    showInput?: boolean;
    showOutput?: boolean;
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
    /** Hive sub-agent identity (related_subagent / subagent_id / worker_id / agent_id). */
    relatedSubagent?: string;
}

export const mergeActivityTargetFields = (
    existing: ActivityItem,
    incoming: Omit<ActivityItem, 'id' | 'number'>
) => ({
    summary: String(incoming.summary || '').trim() || existing.summary,
    command: String(incoming.command || '').trim() || existing.command,
    files: incoming.files?.filter(Boolean).length ? incoming.files : existing.files,
    operation: String(incoming.operation || '').trim() || existing.operation,
    detail: String(incoming.detail || '').trim() || existing.detail
});

export type PanelMode = 'workspace' | 'hive' | 'agent' | 'activity' | 'question' | 'approval' | 'plan' | 'mcp';

export interface PendingQuestion {
    id: string;
    prompt: string;
    options: string[];
    allowCustom?: boolean;
}

export interface PendingApproval {
    id?: string;
    requestId: string;
    tool: string;
    action: string;
    reason?: string;
    sessionId?: string;
    turnId?: string;
    expiresAt?: number;
    title?: string;
    status?: string;
}

export const voicePhaseLabel = (phase: string) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'off') return 'off';
    if (normalized === 'ready') return 'ready';
    if (normalized === 'starting') return 'starting';
    if (normalized === 'listening') return 'listening';
    if (normalized === 'waiting') return 'waiting';
    if (normalized === 'hearing') return 'hearing';
    if (normalized === 'processing') return 'processing';
    if (normalized === 'speaking') return 'speaking';
    if (normalized === 'paused') return 'paused';
    if (normalized === 'stopped') return 'stopped';
    if (normalized === 'error') return 'error';
    if (normalized === 'idle') return 'idle';
    return normalized.replace(/_/g, ' ');
};

export const voicePhaseColor = (phase: string) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'error') return 'red';
    if (normalized === 'speaking' || normalized === 'processing' || normalized === 'hearing') return NEXUS_ORANGE;
    if (normalized === 'waiting' || normalized === 'listening' || normalized === 'ready') return 'green';
    if (normalized === 'paused') return NEXUS_ORANGE_BRIGHT;
    if (normalized === 'starting') return NEXUS_BLUE_BRIGHT;
    if (normalized === 'off' || normalized === 'stopped' || normalized === 'idle') return 'grey30';
    return NEXUS_BLUE;
};

export const voiceBarsForFrame = (phase: string, frame: number, count = 10) => {
    const normalized = String(phase || 'off').toLowerCase();
    if (normalized === 'off' || normalized === 'stopped' || normalized === 'idle') {
        return Array.from({length: count}, () => 1);
    }

    const amplitude = normalized === 'speaking'
        ? 5.4
        : normalized === 'hearing'
            ? 6.0
            : normalized === 'processing'
                ? 4.2
                : 3.0;
    const speed = normalized === 'speaking'
        ? 0.62
        : normalized === 'hearing'
            ? 0.78
            : normalized === 'processing'
                ? 0.42
                : 0.24;

    return Array.from({length: count}, (_, index) => {
        const waveA = Math.sin((frame * speed) + index * 0.82);
        const waveB = Math.sin((frame * (speed * 0.57)) + index * 1.41 + 1.2);
        const raw = Math.abs(waveA * 0.7 + waveB * 0.3);
        return Math.max(1, Math.min(8, Math.round(1 + raw * amplitude)));
    });
};

export const MAX_TIMELINE_ITEMS = 32;
export const CONTEXT_BAR_WIDTH = 24;
export const THEME = {
    appBg: '#181b21',
    panelBg: '#181b21',
    panelAltBg: '#181b21',
    panelSoftBg: '#151820',
    inputBg: '#242833',
    paletteBg: '#202228',
    border: '#262a33',
    borderSoft: '#20242c',
    accent: NEXUS_BLUE
};
export type WorkingPhase =
    | 'thinking'
    | 'querying'
    | 'streaming'
    | 'tool'
    | 'skill'
    | 'plugin'
    | 'mcp'
    | 'hive'
    | 'config'
    | 'settings'
    | 'compact'
    | 'evolution'
    | 'self_improvement'
    | 'knowledge'
    | 'memory'
    | 'no_planning'
    | 'simple_planning'
    | 'advance_planning'
    | 'auditing'
    | 'verifying'
    | 'working';

export const WORKING_STATES: Record<WorkingPhase, {frames: string[]; label: string; action: string; status: string; color: string}> = {
    thinking: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: NEXUS_BLUE},
    querying: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: NEXUS_BLUE},
    streaming: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: NEXUS_BLUE},
    tool: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'green'},
    skill: {frames: ['✦', '✧', '✦', '✧'], label: 'skills', action: 'use', status: 'working', color: NEXUS_BLUE_BRIGHT},
    plugin: {frames: ['⟐', '⟡', '⟐', '⟡'], label: 'plugins', action: 'bind', status: 'working', color: NEXUS_ORANGE_BRIGHT},
    mcp: {frames: ['⎇', '⎉', '⎇', '⎉'], label: 'mcp', action: 'link', status: 'working', color: NEXUS_BLUE_BRIGHT},
    hive: {frames: ['⬡', '⬢', '⬡', '⬢'], label: 'hive', action: 'sync', status: 'working', color: 'blueBright'},
    config: {frames: ['◇', '◈', '◇', '◈'], label: 'config', action: 'set', status: 'working', color: NEXUS_ORANGE},
    settings: {frames: ['⚙', '⚙', '⚙', '⚙'], label: 'settings', action: 'tune', status: 'working', color: NEXUS_BLUE},
    compact: {frames: ['◇◇→◇', '◇◇→◆', '◇→◆', '◆'], label: 'compact', action: '', status: 'compressing', color: NEXUS_ORANGE_BRIGHT},
    evolution: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    self_improvement: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    knowledge: {frames: ['✦', '✧', '✦', '✧'], label: 'skills', action: 'use', status: 'working', color: NEXUS_ORANGE},
    memory: {frames: ['◇◇→◇', '◇◇→◆', '◇→◆', '◆'], label: 'compact', action: '', status: 'compressing', color: NEXUS_ORANGE_BRIGHT},
    no_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: 'grey'},
    simple_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: NEXUS_BLUE},
    advance_planning: {frames: ['●─◌─◌', '◌─●─◌', '◌─◌─●', '◌─●─◌'], label: 'thinking', action: '', status: '', color: NEXUS_BLUE_BRIGHT},
    auditing: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: NEXUS_ORANGE_BRIGHT},
    verifying: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'greenBright'},
    working: {frames: ['◆', '◇', '◆', '◇'], label: 'tools', action: 'run', status: 'working', color: 'white'}
};
export const READ_TOOLS = new Set(['read', 'glob', 'grep', 'find', 'ls', 'diagnostics', 'warpgrep']);
export const WRITE_TOOLS = new Set(['edit', 'write', 'patch', 'multi_edit', 'multiedit', 'apply_patch', 'file_edit', 'write_file']);
export const RUN_TOOLS = new Set(['bash', 'shell', 'exec', 'run', 'run_command', 'terminal', 'powershell', 'cmd']);
export const SEARCH_TOOLS = new Set(['search', 'web_search', 'websearch', 'browser_search', 'grep', 'warpgrep']);
export const TODO_TOOLS = new Set(['todo', 'todo_write', 'task', 'task_update', 'update_plan', 'plan']);

export interface CommandDefinition {
    name: string;
    description: string;
    category: string;
    aliases: string[];
    args: Record<string, string>;
    execution: string;
}

const normalizeCommandName = (value: unknown): string => {
    const name = String(value || '').trim().toLowerCase();
    if (!name) return '';
    return name.startsWith('/') ? name : `/${name}`;
};

/** Convert the server registry response into safe, consistently shaped palette rows. */
export const normalizeCommandRegistry = (payload: unknown): CommandDefinition[] => {
    const rows = Array.isArray(payload)
        ? payload
        : Array.isArray((payload as {commands?: unknown[]})?.commands)
            ? (payload as {commands: unknown[]}).commands
            : [];
    const seen = new Set<string>();
    const commands: CommandDefinition[] = [];
    for (const row of rows) {
        if (!row || typeof row !== 'object') continue;
        const item = row as Record<string, unknown>;
        const name = normalizeCommandName(item.name);
        if (!name || seen.has(name)) continue;
        seen.add(name);
        const aliases = Array.isArray(item.aliases)
            ? item.aliases.map(normalizeCommandName).filter(Boolean)
            : [];
        const rawArgs = item.args && typeof item.args === 'object' && !Array.isArray(item.args)
            ? item.args as Record<string, unknown>
            : {};
        commands.push({
            name,
            description: String(item.description || ''),
            category: String(item.category || 'general'),
            aliases: [...new Set(aliases)],
            args: Object.fromEntries(Object.entries(rawArgs).map(([key, value]) => [key, String(value)])),
            execution: String(item.execution || 'shared'),
        });
    }
    return commands.sort((left, right) => left.name.localeCompare(right.name));
};

export const commandDefinitionFor = (value: string, commands: CommandDefinition[]) => commands.find(command =>
    command.name === value.toLowerCase() || command.aliases.includes(value.toLowerCase())
);
export const estimateTokens = (value: string) => Math.ceil(value.replace(/\s+/g, ' ').trim().length / 4);

/** A session can have only one live agent turn. Stop and cancel remain available. */
export const canStartTurn = (turnInFlight: boolean, value: string): boolean => {
    if (!turnInFlight) return true;
    const command = value.trim().toLowerCase();
    return command === '/stop' || command === '/cancel';
};
// One shared, restrained active-state animation. This replaces the previous
// phase-specific node chains, diamonds, gears, and pulsing glyphs.
export const CLAUDE_SPINNER_FRAMES = ['·', '*', '+', '*'];
for (const state of Object.values(WORKING_STATES)) state.frames = CLAUDE_SPINNER_FRAMES;

export const formatTokens = (value: number) => {
    if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
    return `${value}`;
};

export const formatContextPercent = (tokens: number, limit: number) => {
    if (limit <= 0 || tokens <= 0) return '0%';
    const percent = (tokens / limit) * 100;
    if (percent < 1) return '<1%';
    return `${Math.min(100, Math.round(percent))}%`;
};

export const compactTaskSubject = (value: string, maxLength = 82) => {
    const normalized = value.replace(/\s+/g, ' ').trim();
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
};

export const taskStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('complete') || normalized.includes('done')) return '✓';
    if (normalized.includes('running') || normalized.includes('progress')) return '◐';
    if (normalized.includes('error') || normalized.includes('fail')) return '!';
    return '□';
};

/** Compact state glyph for a task row: (·/▶/✓/✗/⏸/⛔). Real state only. */
export const taskStateGlyph = (status: string): string => {
    const normalized = String(status || '').toLowerCase();
    if (['done', 'completed', 'success', 'finished', 'complete'].includes(normalized)) return '✓';
    if (['error', 'failed', 'failure'].includes(normalized)) return '✗';
    if (['cancelled', 'canceled', 'aborted'].includes(normalized)) return '⛔';
    if (['blocked', 'paused', 'waiting', 'vetoed'].includes(normalized)) return '⏸';
    if (['running', 'active', 'working', 'in_progress', 'queued', 'pending'].includes(normalized)) return '▶';
    return '·';
};

/** Human label for a task status, blanked for the trivial idle state. */
export const taskStateLabel = (status: string): string => {
    const normalized = String(status || '').toLowerCase().replace(/[_-]+/g, ' ');
    const alias: Record<string, string> = {
        'in_progress': 'running',
        'in progress': 'running',
        queued: 'queued',
        pending: 'pending',
        working: 'running',
        active: 'running',
        completed: 'done',
        finished: 'done',
        success: 'done',
        failed: 'error',
        cancelled: 'cancelled',
        canceled: 'cancelled',
        aborted: 'cancelled'
    };
    return alias[normalized] || normalized;
};

/** Elapsed label for a task observed at `startedAt`, '' when unknown. */
export const taskElapsedLabel = (startedAt?: number): string => {
    if (!startedAt || !Number.isFinite(startedAt)) return '';
    const elapsed = Date.now() - startedAt;
    if (elapsed < 0) return '';
    if (elapsed < 1000) return '0s';
    const totalSeconds = Math.floor(elapsed / 1000);
    if (totalSeconds < 60) return `${totalSeconds}s`;
    const minutes = Math.floor(totalSeconds / 60);
    if (minutes < 60) return `${minutes}m${totalSeconds % 60}s`;
    return `${Math.floor(minutes / 60)}h${minutes % 60}m`;
};

const editDistance = (left: string, right: string) => {
    const matrix = Array.from({length: left.length + 1}, (_, row) => [row, ...Array(right.length).fill(0)]);
    for (let column = 1; column <= right.length; column++) {
        matrix[0][column] = column;
    }
    for (let row = 1; row <= left.length; row++) {
        for (let column = 1; column <= right.length; column++) {
            const cost = left[row - 1] === right[column - 1] ? 0 : 1;
            matrix[row][column] = Math.min(
                matrix[row - 1][column] + 1,
                matrix[row][column - 1] + 1,
                matrix[row - 1][column - 1] + cost
            );
        }
    }
    return matrix[left.length][right.length];
};

export const commandMatches = (query: string, commands: CommandDefinition[]) => {
    const normalized = query.toLowerCase();
    if (!normalized.startsWith('/')) return [];
    if (normalized === '/') return commands.slice(0, 10);

    return commands
        .map(command => {
            const names = [command.name, ...(command.aliases || [])];
            const score = Math.min(...names.map(name => {
                if (name.startsWith(normalized)) return 0;
                if (name.includes(normalized)) return 1;
                return editDistance(normalized.replace('/', ''), name.replace('/', '')) <= 2 ? 2 : 99;
            }));
            return {command, score};
        })
        .filter(item => item.score < 99)
        .sort((a, b) => a.score - b.score || a.command.name.localeCompare(b.command.name))
        .slice(0, 10)
        .map(item => item.command);
};

export const timelineColor = (kind: TimelineKind) => {
    if (kind === 'read') return 'blue';
    if (kind === 'write') return NEXUS_BLUE;
    if (kind === 'tool') return NEXUS_BLUE_BRIGHT;
    if (kind === 'success') return 'green';
    if (kind === 'error') return 'red';
    if (kind === 'text') return 'grey';
    return 'grey30';
};

export const timelineGlyph = (event: TimelineEvent) => {
    if (event.kind === 'error') return '▆';
    if (event.kind === 'success') return '▇';
    if (event.weight >= 220) return '█';
    if (event.weight >= 120) return '▇';
    if (event.weight >= 60) return '▅';
    if (event.weight >= 20) return '▃';
    return '▂';
};

export const classifyTool = (toolName: string): TimelineKind => {
    const normalized = toolName.toLowerCase();
    if (READ_TOOLS.has(normalized)) return 'read';
    if (WRITE_TOOLS.has(normalized)) return 'write';
    return 'tool';
};

export const inferActivityKind = (toolName: string, params: Record<string, any>): ActivityKind => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

    if (blob.includes('approval') || blob.includes('permission')) return 'approval';
    if (blob.includes('retry')) return 'retry';
    if (blob.includes('test') || blob.includes('pytest') || blob.includes('vitest')) return 'test';
    if (blob.includes('browser')) return 'browser';
    if (blob.includes('rag')) return 'rag';
    if (blob.includes('provider')) return 'provider';
    if (blob.includes('background')) return 'background';
    if (blob.includes('compact')) return 'compact';
    if (blob.includes('memory')) return 'memory';
    if (blob.includes('settings') || blob.includes('theme') || blob.includes('statusline') || blob.includes('output-style')) return 'settings';
    if (blob.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(blob)) return 'config';
    if (blob.includes('hive') || blob.includes('worker') || blob.includes('agent')) return 'hive';
    if (blob.includes('skill')) return 'skill';
    if (blob.includes('plugin')) return 'plugin';
    if (blob.includes('mcp')) return 'mcp';
    if (SEARCH_TOOLS.has(normalized) || normalized.includes('search')) return 'search';
    if (TODO_TOOLS.has(normalized) || normalized.includes('todo')) return 'todo';
    if (normalized === 'terminal') return 'terminal';
    if (RUN_TOOLS.has(normalized)) return 'run';
    if (normalized === 'file_edit' || normalized === 'write_file' || WRITE_TOOLS.has(normalized)) return 'file';
    return 'tool';
};

export const inferWorkingPhaseFromTool = (toolName: string, params: Record<string, any>): WorkingPhase => {
    const normalized = toolName.toLowerCase();
    const blob = `${normalized} ${JSON.stringify(params || {})}`.toLowerCase();

    if (blob.includes('compact') || blob.includes('memory')) return 'compact';
    if (blob.includes('settings') || blob.includes('theme') || blob.includes('statusline') || blob.includes('output-style')) return 'settings';
    if (blob.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(blob)) return 'config';
    if (blob.includes('self_improvement') || blob.includes('improvement')) return 'self_improvement';
    if (blob.includes('evolution')) return 'evolution';
    if (blob.includes('knowledge')) return 'knowledge';
    if (blob.includes('audit')) return 'auditing';
    if (blob.includes('verify') || blob.includes('validation') || blob.includes('check')) return 'verifying';
    if (blob.includes('hive') || blob.includes('worker') || blob.includes('agent')) return 'hive';
    if (blob.includes('plugin')) return 'plugin';
    if (blob.includes('skill')) return 'skill';
    if (blob.includes('mcp')) return 'mcp';
    if (blob.includes('advanced_plan') || blob.includes('ultraplan')) return 'advance_planning';
    if (blob.includes('plan')) return 'simple_planning';
    if (RUN_TOOLS.has(normalized) || normalized === 'terminal') return 'working';
    return 'tool';
};

export const inferWorkingPhaseFromText = (text: string): WorkingPhase | null => {
    const normalized = text.toLowerCase();
    if (!normalized.trim()) return null;
    if (normalized.includes('compact') || normalized.includes('compress')) return 'compact';
    if (normalized.includes('settings') || normalized.includes('theme') || normalized.includes('statusline') || normalized.includes('output-style')) return 'settings';
    if (normalized.includes('config') || /\.(ya?ml|json|jsnol|toml|env)\b/.test(normalized)) return 'config';
    if (normalized.includes('self improvement')) return 'self_improvement';
    if (normalized.includes('evolution')) return 'evolution';
    if (normalized.includes('memory')) return 'compact';
    if (normalized.includes('knowledge')) return 'knowledge';
    if (normalized.includes('plugin')) return 'plugin';
    if (normalized.includes('skill')) return 'skill';
    if (normalized.includes('mcp')) return 'mcp';
    if (normalized.includes('hive') || normalized.includes('worker')) return 'hive';
    if (normalized.includes('auditing') || normalized.includes('audit')) return 'auditing';
    if (normalized.includes('verify') || normalized.includes('checking')) return 'verifying';
    if (normalized.includes('advanced plan') || normalized.includes('step by step plan')) return 'advance_planning';
    if (normalized.includes('plan')) return 'simple_planning';
    if (normalized.includes('working')) return 'working';
    return null;
};

export const statusColor = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('error') || normalized.includes('fail')) return 'red';
    if (normalized.includes('done') || normalized.includes('complete')) return 'green';
    if (normalized.includes('progress') || normalized.includes('running')) return NEXUS_BLUE;
    return 'grey30';
};

export const activityStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('error') || normalized.includes('fail')) return '×';
    if (normalized.includes('done') || normalized.includes('complete') || normalized.includes('success')) return '✓';
    if (normalized.includes('blocked')) return '!';
    if (normalized.includes('cancel')) return '−';
    if (normalized.includes('running') || normalized.includes('progress') || normalized.includes('queued') || normalized.includes('pending')) return '•';
    return '·';
};

export const activityColor = (kind: ActivityKind) => {
    if (kind === 'file') return 'grey';
    if (kind === 'search') return 'blueBright';
    if (kind === 'todo') return 'green';
    if (kind === 'plan') return NEXUS_ORANGE_BRIGHT;
    if (kind === 'test') return 'greenBright';
    if (kind === 'browser') return NEXUS_BLUE_BRIGHT;
    if (kind === 'approval' || kind === 'retry') return NEXUS_ORANGE_BRIGHT;
    if (kind === 'error') return 'red';
    if (kind === 'provider') return NEXUS_BLUE_BRIGHT;
    if (kind === 'rag' || kind === 'memory') return 'blueBright';
    if (kind === 'background') return 'grey';
    if (kind === 'run' || kind === 'terminal') return NEXUS_BLUE;
    if (kind === 'mcp') return NEXUS_ORANGE;
    if (kind === 'skill') return NEXUS_BLUE_BRIGHT;
    if (kind === 'plugin') return NEXUS_ORANGE;
    if (kind === 'hive') return NEXUS_ORANGE_BRIGHT;
    if (kind === 'config') return NEXUS_ORANGE;
    if (kind === 'settings') return NEXUS_BLUE;
    if (kind === 'compact') return NEXUS_ORANGE_BRIGHT;
    return NEXUS_BLUE_BRIGHT;
};

export const activityGlyph = (kind: ActivityKind) => {
    if (kind === 'file') return '✎';
    if (kind === 'search') return '⌕';
    if (kind === 'todo') return '☑';
    if (kind === 'plan') return '☰';
    if (kind === 'test') return '#';
    if (kind === 'browser') return '@';
    if (kind === 'approval') return '!';
    if (kind === 'error') return '!';
    if (kind === 'retry') return '~';
    if (kind === 'provider') return 'P';
    if (kind === 'rag') return 'R';
    if (kind === 'memory') return 'M';
    if (kind === 'background') return '~';
    if (kind === 'run' || kind === 'terminal') return '▹';
    if (kind === 'mcp') return '◇';
    if (kind === 'skill') return '✦';
    if (kind === 'plugin') return '⟐';
    if (kind === 'hive') return '⬡';
    if (kind === 'config') return '◇';
    if (kind === 'settings') return '⚙';
    if (kind === 'compact') return '◆';
    return '◦';
};

export const IDENTITY_LOGOS = ['⠶', '⡇', '⠿', '⟐', '◈', '⎇', '⌬', '✦', '⬡', '◆', '◇', '⌁', '⟒', '⊕', '⊖'];
export const IDENTITY_COLORS = [NEXUS_BLUE, NEXUS_ORANGE, NEXUS_BLUE_BRIGHT, NEXUS_ORANGE_BRIGHT];

const stableHash = (value: string) => {
    let hash = 2166136261;
    for (const char of value) {
        hash ^= char.charCodeAt(0);
        hash = Math.imul(hash, 16777619);
    }
    return Math.abs(hash >>> 0);
};

export const cleanIdentityName = (value: unknown) => String(value || '')
    .trim()
    .replace(/^mcp[.:/_-]/i, '')
    .replace(/^skill[.:/_-]/i, '')
    .replace(/^plugin[.:/_-]/i, '')
    .replace(/^tool[.:/_-]/i, '')
    .replace(/^hive[.:/_-]/i, '')
    .replace(/\\/g, '/')
    .split('/')
    .pop() || '';

export type ActivityDisplayMeta = Partial<{
    logo: string;
    color: string;
    short: string;
    name: string;
    showSources: boolean;
    showInput: boolean;
    showOutput: boolean;
    maxPreviewLines: number;
    maxPreviewChars: number;
    intent: string;
    rules: string[];
    conditions: string[];
    oneTimeUse: boolean;
    maxPerTask: number;
    parallel: boolean;
    maxParallel: number;
    cooldownMs: number;
}>;

const parseOptionalBool = (value: unknown): boolean | undefined => {
    if (typeof value === 'boolean') return value;
    const normalized = String(value ?? '').trim().toLowerCase();
    if (['true', 'yes', 'on', '1'].includes(normalized)) return true;
    if (['false', 'no', 'off', '0'].includes(normalized)) return false;
    return undefined;
};

const parseOptionalNumber = (value: unknown): number | undefined => {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
};

const parseOptionalStringList = (value: unknown): string[] | undefined => {
    if (Array.isArray(value)) {
        const list = value.map(item => String(item ?? '').trim()).filter(Boolean);
        return list.length > 0 ? list : undefined;
    }
    const raw = String(value ?? '').trim();
    if (!raw) return undefined;
    const list = raw.split(/\s*(?:;|,|\n)\s*/).map(item => item.trim()).filter(Boolean);
    return list.length > 0 ? list : undefined;
};

const readIdentityMetaFile = (filePath: string): ActivityDisplayMeta => {
    if (!existsSync(filePath)) return {};
    try {
        const raw = readFileSync(filePath, 'utf8');
        const json = raw.trim().startsWith('{') ? JSON.parse(raw) : null;
        if (json) {
            const constitution = json.constitution || {};
            const activity = json.activity || {};
            const execution = json.execution || json.runtime || {};
            const pick = (snake: string, camel?: string) =>
                constitution[snake] ?? (camel ? constitution[camel] : undefined) ??
                execution[snake] ?? (camel ? execution[camel] : undefined) ??
                activity[snake] ?? (camel ? activity[camel] : undefined) ??
                json[snake] ?? (camel ? json[camel] : undefined);
            return {
                logo: json.logo || json.icon || json.glyph,
                color: json.color || json.logoColor || json.logo_color,
                short: json.short || json.shortName || json.short_name,
                name: json.name || json.id,
                showSources: parseOptionalBool(pick('show_sources', 'showSources')),
                showInput: parseOptionalBool(pick('show_input', 'showInput')),
                showOutput: parseOptionalBool(pick('show_output', 'showOutput')),
                maxPreviewLines: parseOptionalNumber(pick('max_preview_lines', 'maxPreviewLines')),
                maxPreviewChars: parseOptionalNumber(pick('max_preview_chars', 'maxPreviewChars')),
                intent: pick('intent'),
                rules: parseOptionalStringList(pick('rules')),
                conditions: parseOptionalStringList(pick('conditions')),
                oneTimeUse: parseOptionalBool(pick('one_time_use', 'oneTimeUse')),
                maxPerTask: parseOptionalNumber(pick('max_per_task', 'maxPerTask')),
                parallel: parseOptionalBool(pick('parallel')),
                maxParallel: parseOptionalNumber(pick('max_parallel', 'maxParallel')),
                cooldownMs: parseOptionalNumber(pick('cooldown_ms', 'cooldownMs'))
            };
        }
        const frontMatter = raw.match(/^---\s*\n([\s\S]*?)\n---/);
        const source = frontMatter ? frontMatter[1] : raw.split(/\r?\n/).slice(0, 40).join('\n');
        const pick = (key: string) => {
            const match = source.match(new RegExp(`^${key}:\\s*["']?([^"'\\n#]+)`, 'im'));
            return match?.[1]?.trim();
        };
        return {
            logo: pick('logo') || pick('icon') || pick('glyph'),
            color: pick('color') || pick('logoColor') || pick('logo_color'),
            short: pick('short') || pick('shortName') || pick('short_name'),
            name: pick('name') || pick('id'),
            showSources: parseOptionalBool(pick('show_sources') || pick('showSources') || pick('activity.show_sources') || pick('activity.showSources')),
            showInput: parseOptionalBool(pick('show_input') || pick('showInput') || pick('activity.show_input') || pick('activity.showInput')),
            showOutput: parseOptionalBool(pick('show_output') || pick('showOutput') || pick('activity.show_output') || pick('activity.showOutput')),
            maxPreviewLines: parseOptionalNumber(pick('max_preview_lines') || pick('maxPreviewLines') || pick('activity.max_preview_lines') || pick('activity.maxPreviewLines')),
            maxPreviewChars: parseOptionalNumber(pick('max_preview_chars') || pick('maxPreviewChars') || pick('activity.max_preview_chars') || pick('activity.maxPreviewChars')),
            intent: pick('intent') || pick('constitution.intent') || pick('activity.intent') || pick('execution.intent'),
            rules: parseOptionalStringList(pick('rules') || pick('constitution.rules') || pick('activity.rules') || pick('execution.rules')),
            conditions: parseOptionalStringList(pick('conditions') || pick('constitution.conditions') || pick('activity.conditions') || pick('execution.conditions')),
            oneTimeUse: parseOptionalBool(pick('one_time_use') || pick('oneTimeUse') || pick('constitution.one_time_use') || pick('constitution.oneTimeUse')),
            maxPerTask: parseOptionalNumber(pick('max_per_task') || pick('maxPerTask') || pick('constitution.max_per_task') || pick('constitution.maxPerTask')),
            parallel: parseOptionalBool(pick('parallel') || pick('execution.parallel') || pick('activity.parallel')),
            maxParallel: parseOptionalNumber(pick('max_parallel') || pick('maxParallel') || pick('execution.max_parallel') || pick('execution.maxParallel')),
            cooldownMs: parseOptionalNumber(pick('cooldown_ms') || pick('cooldownMs') || pick('execution.cooldown_ms') || pick('execution.cooldownMs'))
        };
    } catch {
        return {};
    }
};

const identityMetaCandidates = (kind: ActivityKind, name: string) => {
    const id = cleanIdentityName(name);
    if (!id) return [];
    const lower = id.toLowerCase();
    const byKind: Partial<Record<ActivityKind, string[]>> = {
        skill: [
            path.join(PROJECT_ROOT, 'skills', id, 'SKILL.md'),
            path.join(PROJECT_ROOT, 'skills', lower, 'SKILL.md')
        ],
        tool: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', id, `${id}.json`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.json`),
            path.join(PROJECT_ROOT, 'tools', id, `${id}.md`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.md`)
        ],
        terminal: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'terminal', 'terminal.jsnol')
        ],
        run: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'terminal', 'terminal.jsnol')
        ],
        search: [
            path.join(PROJECT_ROOT, 'tools', id, `${id}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', lower, `${lower}.jsnol`),
            path.join(PROJECT_ROOT, 'tools', 'web_search', 'web_search.jsnol'),
            path.join(PROJECT_ROOT, 'tools', 'code_search', 'code_search.jsnol')
        ],
        mcp: [
            path.join(PROJECT_ROOT, 'mcp', id, `${id}.json`),
            path.join(PROJECT_ROOT, 'mcp', lower, `${lower}.json`),
            path.join(PROJECT_ROOT, 'mcp', id, `${id}.yml`),
            path.join(PROJECT_ROOT, 'mcp', lower, `${lower}.yml`),
            path.join(PROJECT_ROOT, 'mcp', id, 'read.md'),
            path.join(PROJECT_ROOT, 'mcp', lower, 'read.md')
        ],
        plugin: [
            path.join(PROJECT_ROOT, 'plugins', id, 'plugin.json'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'plugin.json'),
            path.join(PROJECT_ROOT, 'plugins', id, 'plugin.yml'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'plugin.yml'),
            path.join(PROJECT_ROOT, 'plugins', id, 'README.md'),
            path.join(PROJECT_ROOT, 'plugins', lower, 'README.md')
        ],
        hive: [
            path.join(PROJECT_ROOT, 'hive', 'agents', id, 'agent.md'),
            path.join(PROJECT_ROOT, 'hive', 'agents', lower, 'agent.md'),
            path.join(PROJECT_ROOT, 'hive', 'agents', id, 'agent.yml'),
            path.join(PROJECT_ROOT, 'hive', 'agents', lower, 'agent.yml')
        ],
        config: [path.join(PROJECT_ROOT, 'config', id)],
        settings: [path.join(PROJECT_ROOT, 'config', 'settings.yml')],
        compact: [path.join(PROJECT_ROOT, 'context', 'compressor.py')]
    };
    return byKind[kind] || [];
};

export const resolveActivityIdentity = (kind: ActivityKind, name: string) => {
    const id = cleanIdentityName(name) || kind;
    const key = `${kind}:${id.toLowerCase()}`;
    for (const candidate of identityMetaCandidates(kind, id)) {
        const meta = readIdentityMetaFile(candidate);
        if (
            meta.logo || meta.color || meta.short || meta.name ||
            meta.showSources !== undefined || meta.showInput !== undefined || meta.showOutput !== undefined ||
            meta.maxPreviewLines !== undefined || meta.maxPreviewChars !== undefined ||
            meta.intent || meta.rules || meta.conditions || meta.oneTimeUse !== undefined || meta.maxPerTask !== undefined ||
            meta.parallel !== undefined || meta.maxParallel !== undefined || meta.cooldownMs !== undefined
        ) {
            return {
                logo: (meta.logo || activityGlyph(kind)).trim(),
                color: meta.color || activityColor(kind),
                label: meta.short || meta.name || id,
                showSources: meta.showSources,
                showInput: meta.showInput,
                showOutput: meta.showOutput,
                maxPreviewLines: meta.maxPreviewLines,
                maxPreviewChars: meta.maxPreviewChars,
                intent: meta.intent,
                rules: meta.rules,
                conditions: meta.conditions,
                oneTimeUse: meta.oneTimeUse,
                maxPerTask: meta.maxPerTask,
                parallel: meta.parallel,
                maxParallel: meta.maxParallel,
                cooldownMs: meta.cooldownMs
            };
        }
    }
    const hash = stableHash(key);
    return {
        logo: IDENTITY_LOGOS[hash % IDENTITY_LOGOS.length],
        color: IDENTITY_COLORS[hash % IDENTITY_COLORS.length],
        label: id,
        showSources: undefined,
        showInput: undefined,
        showOutput: undefined,
        maxPreviewLines: undefined,
        maxPreviewChars: undefined,
        intent: undefined,
        rules: undefined,
        conditions: undefined,
        oneTimeUse: undefined,
        maxPerTask: undefined,
        parallel: undefined,
        maxParallel: undefined,
        cooldownMs: undefined
    };
};

const activityActionIdentity = (activity: Omit<ActivityItem, 'id' | 'number'>) => {
    const operation = String(activity.operation || activity.title || activity.toolName || '').toLowerCase();
    if (activity.kind === 'file') {
        if (operation.includes('read') || operation.includes('view')) return {logo: '→', color: 'grey'};
        if (operation.includes('create') || operation.includes('write')) return {logo: '+', color: 'greenBright'};
        if (operation.includes('delete') || operation.includes('remove')) return {logo: '×', color: 'red'};
        return {logo: '✎', color: NEXUS_ORANGE_BRIGHT};
    }
    if (activity.kind === 'search') return {logo: '⌕', color: 'blueBright'};
    if (activity.kind === 'run' || activity.kind === 'terminal') return {logo: '$', color: NEXUS_BLUE_BRIGHT};
    if (activity.kind === 'todo') return {logo: '☑', color: 'green'};
    if (activity.kind === 'config') return {logo: '◇', color: NEXUS_ORANGE};
    if (activity.kind === 'settings') return {logo: '⚙', color: NEXUS_BLUE};
    if (activity.kind === 'compact') return {logo: '◆', color: NEXUS_ORANGE_BRIGHT};
    if (activity.kind === 'tool') return {logo: '◆', color: 'green'};
    return null;
};

export const withActivityIdentity = <T extends Omit<ActivityItem, 'id' | 'number'>>(activity: T): T => {
    const identityName = activity.toolName || activity.summary || activity.title || activity.kind;
    const identity = resolveActivityIdentity(activity.kind, identityName);
    const actionIdentity = activityActionIdentity(activity);
    if (actionIdentity) {
        return {
            ...activity,
            logo: activity.logo || actionIdentity.logo,
            logoColor: activity.logoColor || actionIdentity.color,
            showSources: activity.showSources ?? identity.showSources,
            showInput: activity.showInput ?? identity.showInput,
            showOutput: activity.showOutput ?? identity.showOutput,
            maxPreviewLines: activity.maxPreviewLines ?? identity.maxPreviewLines,
            maxPreviewChars: activity.maxPreviewChars ?? identity.maxPreviewChars,
            intent: activity.intent ?? identity.intent,
            rules: activity.rules ?? identity.rules,
            conditions: activity.conditions ?? identity.conditions,
            oneTimeUse: activity.oneTimeUse ?? identity.oneTimeUse,
            maxPerTask: activity.maxPerTask ?? identity.maxPerTask,
            parallel: activity.parallel ?? identity.parallel,
            maxParallel: activity.maxParallel ?? identity.maxParallel,
            cooldownMs: activity.cooldownMs ?? identity.cooldownMs
        };
    }
    return {
        ...activity,
        logo: activity.logo || identity.logo,
        logoColor: activity.logoColor || identity.color,
        showSources: activity.showSources ?? identity.showSources,
        showInput: activity.showInput ?? identity.showInput,
        showOutput: activity.showOutput ?? identity.showOutput,
        maxPreviewLines: activity.maxPreviewLines ?? identity.maxPreviewLines,
        maxPreviewChars: activity.maxPreviewChars ?? identity.maxPreviewChars,
        intent: activity.intent ?? identity.intent,
        rules: activity.rules ?? identity.rules,
        conditions: activity.conditions ?? identity.conditions,
        oneTimeUse: activity.oneTimeUse ?? identity.oneTimeUse,
        maxPerTask: activity.maxPerTask ?? identity.maxPerTask,
        parallel: activity.parallel ?? identity.parallel,
        maxParallel: activity.maxParallel ?? identity.maxParallel,
        cooldownMs: activity.cooldownMs ?? identity.cooldownMs
    };
};

export const getFileName = (value: string) => value.split(/[/\\]/).pop() || value;

export const cleanPreview = (value: unknown, lines = 14) => String(value || '')
    .replace(/\r\n/g, '\n')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
    .replace(/(?:\x1b)?\[<\d+;\d+;\d+[mM]/g, '')
    .split('\n')
    .slice(0, lines)
    .join('\n')
    .trim();

export const codePreviewLines = (value: string, limit = 36) => cleanPreview(value, limit)
    .split('\n')
    .filter((line, index, lines) => line.length > 0 || index < lines.length - 1)
    .map((line, index) => `${String(index + 1).padStart(3, ' ')}  ${line}`);

export const compactDetailPreview = (value: unknown, lines = 10, chars = 1200) => {
    const cleaned = cleanPreview(value, lines);
    return cleaned.length > chars ? `${cleaned.slice(0, chars).trimEnd()}…` : cleaned;
};

export const formatDurationMs = (value?: number) => {
    if (value == null || !Number.isFinite(value) || value < 0) return '';
    if (value < 1000) return `${Math.round(value)}ms`;
    const seconds = Math.round(value / 1000);
    if (seconds < 60) return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)}s`;
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return `${minutes}m ${String(remainder).padStart(2, '0')}s`;
};

export const normalizeActivityStatus = (status: unknown, error?: unknown) => {
    const value = String(status || '').toLowerCase();
    if (value.includes('block') || value.includes('guardrail') || value.includes('denied')) return 'blocked';
    if (error || value.includes('error') || value.includes('fail') || value.includes('exception')) return 'error';
    if (value === 'success' || value === 'succeeded' || value === 'complete' || value === 'completed') return 'done';
    if (value === 'in_progress' || value === 'started') return 'running';
    if (value === 'cancelled' || value === 'canceled') return 'cancelled';
    return value || 'running';
};

export const extractUrls = (value: unknown) => {
    const matches = String(value || '').match(/https?:\/\/[^\s)\]]+|www\.[^\s)\]]+/g) || [];
    return [...new Set(matches.map(url => url.replace(/[.,;:]+$/, '')))].slice(0, 8);
};

export const compactActivityOutputPreview = (activity: ActivityItem) => {
    const raw = activity.error
        || (activity.showOutput !== false ? (activity.output || activity.preview) : '')
        || (activity.showInput !== false ? activity.detail : '')
        || '';
    const lineLimit = activity.maxPreviewLines ?? (activity.kind === 'search' ? 5 : 8);
    const charLimit = activity.maxPreviewChars ?? (activity.kind === 'search' ? 520 : 900);
    const scrubbed = String(raw)
        .replace(/\]\(https?:\/\/[^)]+\)/g, ']')
        .replace(/https?:\/\/\S+/g, '<link>')
        .replace(/www\.\S+/g, '<link>')
        .replace(/\s+/g, ' ')
        .trim();
    return compactDetailPreview(scrubbed, lineLimit, charLimit);
};

export const activityPreviewLabel = (activity: ActivityItem) => {
    if (activity.error) return 'error';
    if (activity.kind === 'search') return 'results';
    if (activity.output) return 'output';
    if (activity.preview) return 'preview';
    return 'input';
};

export const formatToolInput = (params: Record<string, any>) => Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .filter(([key]) => !['file_text', 'content', 'new_str', 'new_string', 'old_str'].includes(key))
    .map(([key, value]) => `${key}: ${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('\n');

export const runLocal = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
    try {
        const {stdout, stderr} = await execFileAsync(file, args, {
            cwd,
            timeout,
            windowsHide: true,
            maxBuffer: 1024 * 1024
        });
        return cleanPreview([stdout, stderr].filter(Boolean).join('\n'), 80);
    } catch (error: any) {
        const output = [error.stdout, error.stderr, error.message].filter(Boolean).join('\n');
        return cleanPreview(output, 80);
    }
};

export const runLocalResult = async (file: string, args: string[], cwd = PROJECT_ROOT, timeout = 20000) => {
    try {
        const {stdout, stderr} = await execFileAsync(file, args, {
            cwd,
            timeout,
            windowsHide: true,
            maxBuffer: 1024 * 1024
        });
        return {ok: true, output: cleanPreview([stdout, stderr].filter(Boolean).join('\n'), 80)};
    } catch (error: any) {
        const output = [error.stdout, error.stderr, error.message].filter(Boolean).join('\n');
        return {ok: false, output: cleanPreview(output, 80)};
    }
};

export const startDetached = (file: string, args: string[], cwd = PROJECT_ROOT, env?: NodeJS.ProcessEnv) => {
    const child = spawn(file, args, {
        cwd,
        env: env ? {...process.env, ...env} : process.env,
        detached: true,
        stdio: 'ignore',
        windowsHide: true
    });
    child.unref();
};

export const apiHasTuiCapabilities = async () => {
    try {
        const [health, status, voice] = await Promise.all([
            fetch(`${API_BASE}/health`, {headers: API_AUTH_HEADERS}),
            fetch(`${API_BASE}/status`, {headers: API_AUTH_HEADERS}),
            fetch(`${API_BASE}/voice/status`, {headers: API_AUTH_HEADERS})
        ]);
        return health.ok && status.ok && voice.ok;
    } catch {
        return false;
    }
};

export const clearApiPortForRestart = async () => {
    if (process.platform !== 'win32') return;
    const command = [
        '$ErrorActionPreference = "SilentlyContinue"',
        '$pids = netstat -ano | Select-String ":8000\\s+.*LISTENING" | ForEach-Object { ($_ -split "\\s+")[-1] } | Sort-Object -Unique',
        'foreach ($id in $pids) { if ($id -match "^\\d+$") { taskkill /F /PID $id | Out-Null } }'
    ].join('; ');
    try {
        await execFileAsync('powershell.exe', ['-NoProfile', '-Command', command], {
            cwd: PROJECT_ROOT,
            timeout: 5000,
            windowsHide: true
        });
    } catch {
        // Best effort; the subsequent server start/poll will report failure if the port stays busy.
    }
};

export const commandExists = async (command: string) => {
    try {
        await execFileAsync(process.platform === 'win32' ? 'where' : 'which', [command], {
            cwd: PROJECT_ROOT,
            timeout: 5000,
            windowsHide: true
        });
        return true;
    } catch {
        return false;
    }
};

export const safeRelativePath = (input: string) => {
    const target = path.resolve(PROJECT_ROOT, input || '.');
    const root = path.resolve(PROJECT_ROOT);
    if (!target.startsWith(root)) {
        throw new Error('Path escapes workspace');
    }
    return target;
};

const normalizeAttachmentPath = (value: string) => {
    let cleaned = value.trim().replace(/^@/, '').replace(/^['"]|['"]$/g, '');
    cleaned = cleaned.replace(/[),.;]+$/g, '');
    if (cleaned.startsWith('file:///')) {
        cleaned = decodeURIComponent(cleaned.replace(/^file:\/\/\//, ''));
        if (/^[A-Za-z]\|/.test(cleaned)) {
            cleaned = `${cleaned[0]}:${cleaned.slice(2)}`;
        }
    }
    return path.isAbsolute(cleaned) ? path.resolve(cleaned) : path.resolve(PROJECT_ROOT, cleaned);
};

const extractAttachmentCandidates = (value: string) => {
    const candidates = new Set<string>();
    const quoted = value.matchAll(/["']([^"']+)["']/g);
    for (const match of quoted) candidates.add(match[1]);

    const fileUrls = value.matchAll(/file:\/\/\/[^\s"'<>]+/gi);
    for (const match of fileUrls) candidates.add(match[0]);

    const atPaths = value.matchAll(/@([^\s]+)/g);
    for (const match of atPaths) candidates.add(match[1]);

    const trimmed = value.trim();
    if (trimmed) candidates.add(trimmed);

    return [...candidates];
};

export const resolveInputAttachments = async (value: string) => {
    const seen = new Set<string>();
    const files: Array<{path: string; name: string; size: number; kind: string}> = [];

    for (const candidate of extractAttachmentCandidates(value)) {
        try {
            const resolved = normalizeAttachmentPath(candidate);
            if (seen.has(resolved) || !existsSync(resolved)) continue;
            const info = await stat(resolved);
            if (!info.isFile()) continue;
            seen.add(resolved);
            files.push({
                path: resolved,
                name: path.basename(resolved),
                size: info.size,
                kind: path.extname(resolved).replace('.', '').toLowerCase() || 'file'
            });
        } catch {
            // Ignore non-path text; normal chat should keep working.
        }
    }

    return files;
};

export const attachmentPrompt = (prompt: string, files: Array<{path: string; name: string; size: number; kind: string}>) => {
    if (files.length === 0) return prompt;
    const cleanPrompt = prompt.trim() || 'Please inspect the attached file(s).';
    const fileLines = files.map(file => `- ${file.name} (${file.kind}, ${formatTokens(file.size)}B): ${file.path}`);
    return `${cleanPrompt}\n\nAttached files:\n${fileLines.join('\n')}`;
};

export const saveClipboardImage = async () => {
    const uploadDir = path.join(PROJECT_ROOT, 'workspace', 'uploads');
    await mkdir(uploadDir, {recursive: true});
    const output = path.join(uploadDir, `clipboard-${Date.now()}.png`);
    const script = [
        'Add-Type -AssemblyName System.Windows.Forms',
        'Add-Type -AssemblyName System.Drawing',
        '$img = [System.Windows.Forms.Clipboard]::GetImage()',
        'if ($null -eq $img) { exit 2 }',
        `$img.Save(${JSON.stringify(output)}, [System.Drawing.Imaging.ImageFormat]::Png)`,
        '$img.Dispose()'
    ].join('; ');

    await execFileAsync('powershell.exe', ['-NoProfile', '-STA', '-Command', script], {
        cwd: PROJECT_ROOT,
        timeout: 15000,
        windowsHide: true
    });

    return output;
};

export const listDirectory = async (target: string, limit = 40) => {
    const entries = await readdir(target, {withFileTypes: true});
    return entries
        .filter(entry => !['node_modules', '.git', '__pycache__', '.venv'].includes(entry.name))
        .slice(0, limit)
        .map(entry => `${entry.isDirectory() ? '[DIR] ' : '      '}${entry.name}`)
        .join('\n');
};

export const treeDirectory = async (target: string, depth = 2, prefix = ''): Promise<string[]> => {
    if (depth <= 0) return [];
    const entries = (await readdir(target, {withFileTypes: true}))
        .filter(entry => !['node_modules', '.git', '__pycache__', '.venv'].includes(entry.name))
        .slice(0, 24);
    const lines: string[] = [];
    for (const entry of entries) {
        lines.push(`${prefix}${entry.isDirectory() ? '+ ' : '- '}${entry.name}`);
        if (entry.isDirectory()) {
            lines.push(...await treeDirectory(path.join(target, entry.name), depth - 1, `${prefix}  `));
        }
    }
    return lines;
};

export const readYamlSectionNames = async (filePath: string) => {
    const content = await readFile(filePath, 'utf8');
    return content
        .split(/\r?\n/)
        .filter(line => /^[A-Za-z0-9_.-]+:\s*$/.test(line))
        .map(line => line.replace(':', '').trim());
};

export const activityFromTool = (toolName: string, params: Record<string, any>): Omit<ActivityItem, 'id' | 'number'> => {
    const normalized = toolName.toLowerCase();
    const kind = inferActivityKind(toolName, params);
    const rawPath = params.path || params.filename || params.file || params.filepath || params.uri || '';
    const fileName = rawPath ? getFileName(String(rawPath)) : '';
    const command = String(params.command || params.cmd || params.script || '');
    const query = String(params.query || params.q || params.pattern || params.search || params.prompt || '');

    if (SEARCH_TOOLS.has(normalized) || normalized.includes('search')) {
        const summary = query || command || toolName;
        return {
            kind: 'search',
            title: normalized.includes('web') || params.url ? 'Searched web' : 'Searched files',
            summary,
            status: 'running',
            command: summary || undefined,
            detail: formatToolInput(params),
            sources: extractUrls(JSON.stringify(params || {})),
            toolName
        };
    }

    if (TODO_TOOLS.has(normalized) || normalized.includes('todo')) {
        return {
            kind: 'plan',
            title: 'Updated todo list',
            summary: query || command || toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (normalized === 'file_edit' || normalized === 'write_file' || WRITE_TOOLS.has(normalized)) {
        const editCommand = String(params.command || '').toLowerCase();
        const preview = cleanPreview(
            params.new_str || params.new_string || params.file_text || params.content || params.old_str,
            120
        );
        const verb = editCommand === 'create' || normalized === 'write_file'
            ? 'Created'
            : editCommand === 'view'
                ? 'Read'
                : 'Edited';
        return {
            kind: 'file',
            title: `${verb} a file`,
            summary: fileName || toolName,
            status: 'running',
            files: fileName ? [fileName] : [],
            operation: editCommand || normalized,
            preview: preview || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'mcp') {
        return {
            kind: 'mcp',
            title: 'MCP call',
            summary: toolName,
            status: 'running',
            command: command || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'skill') {
        return {
            kind: 'skill',
            title: 'Used skill',
            summary: toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'plugin') {
        return {
            kind: 'plugin',
            title: 'Used plugin',
            summary: toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (kind === 'hive') {
        return {
            kind: 'hive',
            title: 'Hive action',
            summary: command || query || toolName,
            status: 'running',
            detail: formatToolInput(params),
            toolName
        };
    }

    if (RUN_TOOLS.has(normalized)) {
        return {
            kind: normalized === 'terminal' ? 'terminal' : 'run',
            title: 'Ran command',
            summary: command || toolName,
            status: 'running',
            command: command || undefined,
            detail: formatToolInput(params),
            toolName
        };
    }

    return {
        kind: 'tool',
        title: `Used ${toolName}`,
        summary: command || fileName || toolName,
        status: 'running',
        command: command || undefined,
        detail: formatToolInput(params),
        toolName
    };
};

export const readTodoMarkdown = async (): Promise<TaskItem[]> => {
    const candidates = [
        path.resolve(process.cwd(), 'workspace', 'todo.md'),
        path.resolve(process.cwd(), '..', 'workspace', 'todo.md')
    ];

    for (const candidate of candidates) {
        try {
            const markdown = await readFile(candidate, 'utf8');
            return markdown
                .split(/\r?\n/)
                .map((line, index) => {
                    const match = line.match(/^\s*-\s+\[([ xX])\]\s+(.+?)\s*$/);
                    if (!match) return null;
                    const checked = match[1].toLowerCase() === 'x';
                    return {
                        id: `todo-md-${index}`,
                        subject: cleanTaskSubject(match[2].replace(/^Phase\s+\d+:\s*/i, '').trim()),
                        status: checked ? 'completed' : 'pending'
                    };
                })
                .filter((task): task is TaskItem => Boolean(task));
        } catch {
            // Try the next likely workspace root.
        }
    }

    return [];
};

export const clearTerminalForInk = () => {
    if (!process.stdout.isTTY) return;
    process.stdout.write('\x1b[2J\x1b[3J\x1b[H');
};

export const extractSsePayload = (frame: string) => frame
    .replace(/\r/g, '')
    .split('\n')
    .filter(line => !line.startsWith('event:'))
    .map(line => line.startsWith('data:') ? line.replace(/^data:\s?/, '') : line)
    .join('\n');

export const cleanVisibleAssistantText = (text: string) => {
    let cleaned = String(text || '');
    cleaned = cleaned.replace(/\[NEXUS_BOOT\]:[^\n]*/g, '');
    cleaned = cleaned.replace(/\[THINKING:[^\]]+\]/g, '');
    cleaned = cleaned.replace(/<thinking>[\s\S]*?<\/thinking>/gi, '');
    cleaned = cleaned.replace(/<\/?thinking>/gi, '');
    // DeepSeek-style full-width DSML envelopes are transport markup, not
    // assistant prose. Remove complete blocks before rendering the TUI.
    cleaned = cleaned.replace(
        /<[^<>]*DSML[^<>]*tool_calls[^>]*>[\s\S]*?<\/[^<>]*DSML[^<>]*tool_calls\s*>/gi,
        ''
    );
    cleaned = cleaned.replace(/TASK_COMPLETE/g, '');
    cleaned = cleaned.replace(/\n{3,}/g, '\n\n');
    return cleaned.trim();
};

export const mouseWheelDirection = (value: string, maxX: number) => {
    const matches = Array.from(value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)[mM]/g));
    for (const match of matches) {
        const button = Number(match[1]);
        const x = Number(match[2]);
        if (!Number.isFinite(button) || !Number.isFinite(x) || x > maxX) continue;
        if ((button & 64) === 0) continue;
        return (button & 1) === 0 ? 1 : -1;
    }
    return 0;
};

export const mouseWheelDirections = (value: string, maxX: number) => {
    const directions: number[] = [];
    for (const match of value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)[mM]/g)) {
        const button = Number(match[1]);
        const x = Number(match[2]);
        if (Number.isFinite(button) && Number.isFinite(x) && x <= maxX && (button & 64) !== 0) {
            directions.push((button & 1) === 0 ? 1 : -1);
        }
    }
    // X10 mouse protocol fallback used by some Windows terminal configurations.
    for (const match of value.matchAll(/\x1b\[M([\s\S])([\s\S])([\s\S])/g)) {
        const button = match[1].charCodeAt(0) - 32;
        const x = match[2].charCodeAt(0) - 32;
        if (x <= maxX && (button & 64) !== 0) directions.push((button & 1) === 0 ? 1 : -1);
    }
    return directions;
};

export const mousePointer = (value: string, maxX: number) => {
    const matches = Array.from(value.matchAll(/\x1b\[<(\d+);(\d+);(\d+)([mM])/g));
    const match = matches[matches.length - 1];
    if (match) {
        const rawButton = Number(match[1]);
        const x = Number(match[2]);
        const y = Number(match[3]);
        const pressed = match[4] === 'M';
        if (!Number.isFinite(rawButton) || !Number.isFinite(x) || !Number.isFinite(y) || x > maxX) return null;
        return {button: pressed ? rawButton & 3 : 35, x, y, pressed};
    }

    // X10 mouse protocol fallback used by some Windows terminal configurations.
    const x10Matches = Array.from(value.matchAll(/\x1b\[M([\s\S])([\s\S])([\s\S])/g));
    const x10Match = x10Matches[x10Matches.length - 1];
    if (!x10Match) return null;
    const rawButton = x10Match[1].charCodeAt(0) - 32;
    const x = x10Match[2].charCodeAt(0) - 32;
    const y = x10Match[3].charCodeAt(0) - 32;
    const button = rawButton & 3;
    const pressed = button !== 3;
    if (!Number.isFinite(rawButton) || !Number.isFinite(x) || !Number.isFinite(y) || x > maxX) return null;
    return {button: pressed ? button : 35, x, y, pressed};
};

export const sanitizeComposerInput = (value: string) => value
    .replace(/(?:\x1b)?\[<\d+;\d+;\d+[mM]/g, '')
    .replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '');

export const parseQuestionMarker = (text: string): PendingQuestion | null => {
    const markerStart = text.indexOf('[QUESTION:');
    if (markerStart < 0) return null;
    try {
        const jsonStart = markerStart + '[QUESTION:'.length;
        const encoded = text.slice(jsonStart);
        let data: any = null;
        // The JSON contains an options array, so a non-greedy `]` regex is
        // incorrect. Try JSON object boundaries until the payload decodes.
        for (let index = encoded.indexOf('}'); index >= 0; index = encoded.indexOf('}', index + 1)) {
            try {
                const candidate = JSON.parse(encoded.slice(0, index + 1));
                if (candidate && typeof candidate === 'object') {
                    data = candidate;
                    break;
                }
            } catch {
                // Nested object/string boundaries are not the payload end.
            }
        }
        if (!data) return null;
        const options = Array.isArray(data.options)
            ? data.options.map((option: unknown) => String(option)).filter(Boolean).slice(0, 8)
            : [];
        if (!data.prompt || options.length === 0) return null;
        return {
            id: `question-${Date.now()}`,
            prompt: String(data.prompt),
            options,
            allowCustom: data.allowCustom !== false
        };
    } catch {
        return null;
    }
};

/** Extract an ask_question result from a canonical tool lifecycle event. */
export const questionFromToolEvent = (input: Record<string, any>): PendingQuestion | null => {
    const event = adaptCanonicalEvent(input || {});
    const tool = String(event.tool || event.name || '').trim().toLowerCase();
    const status = String(event.status || '').trim().toLowerCase();
    if (tool !== 'ask_question' || !['done', 'success', 'completed', 'ok'].includes(status)) return null;

    const structured = event.metadata?.question
        || event.payload?.metadata?.question
        || event.question
        || event.payload?.question;
    if (structured && typeof structured === 'object') {
        return parseQuestionMarker(`[QUESTION:${JSON.stringify(structured)}]`);
    }
    return parseQuestionMarker(String(event.output || event.result || event.payload?.output || event.payload?.result || ''));
};

/** Normalize a live approval request into the inspector's pending state. */
export const approvalFromWorkEvent = (input: Record<string, any>): PendingApproval | null => {
    const event = adaptCanonicalEvent(input || {});
    const eventType = String(event.event_type || event.type || '').trim().toLowerCase();
    const kind = String(event.kind || '').trim().toLowerCase();
    const isApproval = kind === 'approval'
        || kind === 'guardrail'
        || eventType.includes('approval')
        || eventType.includes('permission')
        || eventType.includes('guardrail');
    if (!isApproval) return null;

    const status = String(event.status || '').trim().toLowerCase();
    if (['done', 'success', 'succeeded', 'completed', 'failed', 'denied', 'rejected', 'cancelled', 'canceled'].includes(status)) {
        return null;
    }

    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const requestId = String(event.request_id || event.requestId || event.approval_id || event.id
        || payload.request_id || payload.requestId || payload.approval_id || payload.id || '').trim();
    const tool = String(event.tool || event.tool_name || event.related_tool || event.name
        || payload.tool || payload.tool_name || payload.related_tool || payload.name || '').trim();
    const action = String(event.action || event.target || event.command
        || payload.action || payload.target || payload.command || '').trim();
    if (!requestId || !tool || !action) return null;

    const rawExpiresAt = Number(event.expires_at ?? event.expiresAt);
    return {
        id: requestId,
        requestId,
        tool,
        action,
        reason: String(event.reason || event.message || event.detail || payload.reason || payload.message || payload.detail || '').trim(),
        sessionId: String(event.session_id || event.sessionId || payload.session_id || payload.sessionId || '').trim() || undefined,
        turnId: String(event.turn_id || event.turnId || payload.turn_id || payload.turnId || '').trim() || undefined,
        expiresAt: Number.isFinite(rawExpiresAt)
            ? rawExpiresAt
            : Number.isFinite(Number(payload.expires_at ?? payload.expiresAt))
                ? Number(payload.expires_at ?? payload.expiresAt)
                : undefined
    };
};

export const stripQuestionMarkers = (text: string) => {
    const markerStart = text.indexOf('[QUESTION:');
    if (markerStart < 0) return text;
    const jsonStart = markerStart + '[QUESTION:'.length;
    const encoded = text.slice(jsonStart);
    for (let index = encoded.indexOf('}'); index >= 0; index = encoded.indexOf('}', index + 1)) {
        try {
            JSON.parse(encoded.slice(0, index + 1));
            const afterMarker = encoded.slice(index + 1).replace(/^\]/, '');
            return `${text.slice(0, markerStart)}${afterMarker}`;
        } catch {
            // Continue until the complete JSON object is found.
        }
    }
    return text;
};

export interface ChatLine {
    key: string;
    text: string;
    color: string;
    prefix?: string;
    prefixColor?: string;
    reservePrefix?: boolean;
    bold?: boolean;
    activityId?: string;
    activity?: ActivityItem;
    backgroundColor?: string;
    focused?: boolean;
    expanded?: boolean;
    /** Message surface role; ChatLineView draws the role-colored boxed border. */
    surface?: 'user' | 'assistant';
}

/** Parse the canonical activity envelope exactly as it arrives over SSE. */
export const canonicalActivityFromSseFrame = (frame: string): Record<string, any> | null => {
    const normalized = frame.replace(/\r/g, '');
    const lines = normalized.split('\n');
    const eventType = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
    if (eventType !== 'work_event' && eventType !== 'nexus.event') return null;
    const raw = lines
        .filter(line => line.startsWith('data:'))
        .map(line => line.replace(/^data:\s?/, ''))
        .join('\n');
    if (!raw) return null;
    const payload = JSON.parse(raw);
    return adaptCanonicalEvent(payload.event || payload);
};

export const activityFromWorkEvent = (event: Record<string, any>): Omit<ActivityItem, 'id' | 'number'> => {
    event = adaptCanonicalEvent(event);
    const eventKind = String(event.kind || event.type || 'tool').toLowerCase();
    const toolName = String(event.tool || event.name || event.server || eventKind);
    const details = event.args || event.arguments || event.input;
    const detailObject = details && typeof details === 'object' && !Array.isArray(details) ? details : {};
    const target = String([
        event.target,
        event.query,
        event.path,
        event.file,
        event.file_path,
        event.command,
        event.url,
        event.source_url,
        detailObject.target,
        detailObject.query,
        detailObject.path,
        detailObject.file,
        detailObject.file_path,
        detailObject.command,
        detailObject.url,
        event.related_files?.[0],
        event.related_command
    ].find(value => value != null && String(value).trim()) || '');
    const output = cleanPreview(event.output || event.stdout || event.chunk || event.result || '', 30) || undefined;
    const error = cleanPreview(event.error || event.stderr || event.preview_error || '', 16) || undefined;
    const sourceValues = [
        event.url,
        event.source_url,
        event.sources,
        event.citations,
        event.links,
        target,
        output
    ];
    const relatedSubagent = String(
        event.related_subagent
        || event.subagent_id
        || event.agent_id
        || event.worker_id
        || detailObject.related_subagent
        || detailObject.subagent_id
        || detailObject.agent_id
        || detailObject.worker_id
        || ''
    ).trim() || undefined;
    const inferredKind = inferActivityKind(toolName, event);
    const explicitKinds = new Set<ActivityKind>([
        'tool', 'command', 'file', 'test', 'search', 'browser', 'mcp', 'skill',
        'plugin', 'hive', 'agent', 'worker', 'provider', 'rag', 'approval',
        'error', 'retry', 'plan', 'todo', 'memory', 'background', 'compact',
        'config', 'settings', 'run', 'terminal'
    ]);
    const resolvedKind: ActivityKind = ['hive', 'agent', 'worker'].includes(eventKind)
        ? 'hive'
        : eventKind === 'command'
            ? 'terminal'
            : explicitKinds.has(eventKind as ActivityKind)
                ? eventKind as ActivityKind
                : inferredKind;
    const friendlyTitles: Partial<Record<ActivityKind, string>> = {
        plan: 'Planning work',
        terminal: 'Running terminal command',
        run: 'Running command',
        file: 'Working with files',
        test: 'Running verification',
        search: 'Searching',
        browser: 'Using browser',
        hive: 'Coordinating Hive agents',
        approval: 'Waiting for approval',
        retry: 'Retrying operation',
        error: 'Operation failed',
        skill: 'Using skill',
        mcp: 'Calling MCP tool',
        provider: 'Contacting provider',
        rag: 'Retrieving context',
        memory: 'Reading memory',
        compact: 'Compacting context'
    };
    const common = {
        title: String(event.action || event.title || event.label || friendlyTitles[resolvedKind] || 'Agent activity'),
        summary: target,
        status: normalizeActivityStatus(event.status, error),
        detail: [
            details ? (typeof details === 'string' ? details : JSON.stringify(details, null, 2)) : '',
            event.duration_ms != null ? `duration: ${event.duration_ms} ms` : '',
            event.exit_code != null ? `exit code: ${event.exit_code}` : '',
            event.changed_lines || event.line_changes ? `changed lines: ${JSON.stringify(event.changed_lines || event.line_changes)}` : '',
            event.diff || event.patch || ''
        ].filter(Boolean).join('\n') || undefined,
        output,
        error,
        durationMs: event.duration_ms ?? event.durationMs,
        sources: sourceValues.flatMap(value => Array.isArray(value) ? value.map(String) : extractUrls(value)),
        relatedSubagent,
        toolName
    };
    if (resolvedKind === 'file') return {...common, kind: 'file', files: target ? [target] : [], operation: String(event.operation || event.action || '')};
    if (resolvedKind === 'terminal' || resolvedKind === 'run' || resolvedKind === 'command') {
        return {...common, kind: resolvedKind === 'command' ? 'terminal' : resolvedKind, command: String(event.command || target || '') || undefined};
    }
    if (resolvedKind === 'search' || resolvedKind === 'browser' || resolvedKind === 'rag') {
        return {...common, kind: resolvedKind, command: String(event.query || target || '') || undefined};
    }
    if (resolvedKind === 'plan') {
        const rawItems = Array.isArray(event.items) ? event.items : Array.isArray(event.steps) ? event.steps : [];
        const items = rawItems
            .map((item: unknown) => typeof item === 'string'
                ? item
                : item && typeof item === 'object'
                    ? String((item as Record<string, unknown>).description || (item as Record<string, unknown>).step || (item as Record<string, unknown>).label || '')
                    : String(item || ''))
            .filter(Boolean);
        const planName = items.length > 1 ? 'Advanced Planning' : 'Simple Planning';
        return {
            ...common,
            kind: 'plan',
            title: planName,
            summary: `${items.length || 1} step${items.length === 1 ? '' : 's'}`,
            detail: items.length > 0
                ? items.map((item: string, index: number) => `${index + 1}. ${item}`).join('\n')
                : 'Resolving planning steps…',
            toolName: 'plan'
        };
    }
    if (resolvedKind === 'todo') return {...common, kind: 'todo', preview: cleanPreview(event.preview || event.result || '', 120) || undefined};
    return {...common, kind: resolvedKind};
};
