/* eslint-disable @typescript-eslint/no-unused-vars */
import { Edit2, Search, TerminalSquare, Monitor, BrainCircuit, Database, Cpu, Puzzle, GraduationCap, Activity, CheckCircle2, Wrench } from 'lucide-react';
import type { WorkEvent } from '../types';

export const getWorkActivityIcon = (kind = '') => {
   const normalized = String(kind || '').toLowerCase();
   return normalized === 'file' ? Edit2
      : normalized === 'search' ? Search
      : normalized === 'command' ? TerminalSquare
      : normalized === 'browser' ? Monitor
      : normalized === 'rag' ? BrainCircuit
      : normalized === 'mcp' ? Database
      : normalized === 'reflection' ? BrainCircuit
      : normalized === 'provider' ? Cpu
      : normalized === 'plugin' ? Puzzle
      : normalized === 'skill' ? GraduationCap
      : normalized === 'hive' ? Activity
      : normalized === 'todo' ? CheckCircle2
      : Wrench;
};

export const shortWorkTarget = (value = '', maxLength = 72) => {
   const compact = String(value || '').replace(/\s+/g, ' ').trim();
   if (!compact) return '';
   return compact.length > maxLength ? `${compact.slice(0, maxLength - 3)}...` : compact;
};

export const fileDisplayName = (value = '') => {
   const clean = String(value || '').replace(/^["']|["']$/g, '').replace(/\\/g, '/').trim();
   return clean.split('/').filter(Boolean).pop() || clean;
};

export const resolveWorkActivityTarget = (row: Record<string, unknown>, _artifactPathIndex: Record<string, string> = {}) => {
   const raw = String(row?.target || row?.path || row?.command || row?.query || row?.result || row?.tool || 'open detail').trim();
   for (const [name, path] of Object.entries(_artifactPathIndex)) {
      if (!name || !path || !raw.includes(name) || raw.includes(path)) continue;
      const safePath = path.includes(' ') ? `"${path}"` : path;
      return raw.replace(new RegExp(`(?<![\\w./\\\\-])${name.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\$&')}(?![\\w./\\\\-])`, 'g'), safePath);
   }
   return raw;
};

export const getWorkActivityLabel = (row: Record<string, unknown>) => {
   const kind = String(row?.kind || row?.type || '').toLowerCase();
   const action = String(row?.action || row?.title || row?.tool || '').toLowerCase();
   const target = String(row?.path || row?.target || '').toLowerCase();
   if (String(row?.stage || '').toLowerCase() === 'planning') return 'Planning';
   if (kind === 'task') return action.includes('queue') ? 'Queued task' : 'Task';
   if (kind === 'todo') return 'Planning';
   if (String(row?.role || '').toLowerCase() === 'planning_artifact' || target.endsWith('todo.md')) return 'Planning';
   if (kind === 'search') return 'Searching';
   if (kind === 'rag') return 'Reading context';
   if (kind === 'browser') return 'Browsing';
   if (kind === 'command') return 'Run command';
   if (kind === 'approval') return 'Approval required';
   if (kind === 'retry') return 'Retrying';
   if (kind === 'error') return 'Action failed';
   if (kind === 'test') return 'Running checks';
   if (kind === 'file') {
      if (action.includes('delete') || action.includes('remove')) return 'Delete file';
      if (action.includes('create')) return 'Create file';
      if (action.includes('read') || action.includes('view')) return 'Read file';
      if (action.includes('update')) return 'Update file';
      return 'Edit file';
   }
   if (kind === 'hive') return 'Delegating';
   if (kind === 'mcp') return 'Using MCP';
   if (kind === 'provider') return 'Checking provider';
   if (kind === 'skill') return 'Using skill';
   if (kind === 'plugin') return 'Using plugin';
   if (kind === 'tool') {
      if (action.includes('read')) return 'Reading';
      if (action.includes('list') || action.includes('glob')) return 'Listing';
      if (action.includes('grep') || action.includes('find') || action.includes('search')) return 'Searching';
      if (action.includes('run') || action.includes('execute')) return 'Running tool';
      return 'Using tool';
   }
   return 'Working';
};

export const getWorkActivityTarget = (row: Record<string, unknown>, _artifactPathIndex: Record<string, string> = {}) => {
   const kind = String(row?.kind || row?.type || '').toLowerCase();
   const role = String(row?.role || '').toLowerCase();
   if (String(row?.kind || row?.type || '').toLowerCase() === 'todo') {
      return 'todo.md';
   }
   if (role === 'planning_artifact' || String(row?.path || row?.target || '').toLowerCase().endsWith('todo.md')) {
      return 'todo.md';
   }
   if (kind === 'file') {
      return fileDisplayName(String(row?.path || row?.target || 'file'));
   }
   if (kind === 'command') {
      return shortWorkTarget(String(resolveWorkActivityTarget(row, _artifactPathIndex)), 96);
   }
   const raw = resolveWorkActivityTarget(row, _artifactPathIndex);
   return shortWorkTarget(raw);
};

/** Flatten the canonical envelope while retaining legacy flat-event support. */
export const adaptCanonicalWorkEvent = (input: WorkEvent): WorkEvent => {
   const payload = input.payload && typeof input.payload === 'object' ? input.payload : {};
   const eventType = String(input.event_type || input.type || '').toLowerCase();
   const family = eventType.includes('.') ? eventType.split('.')[0] : '';
   const familyKind = family === 'web' ? 'search'
      : family === 'subagent' || family === 'handoff' ? 'hive'
      : family === 'plan' || family === 'phase' ? 'todo'
      : ['run', 'conversation', 'message', 'status'].includes(family) ? 'task'
      : family;
const errorValue = input.error && typeof input.error === 'object'
      ? input.error.message || JSON.stringify(input.error)
      : input.error;
   const p = payload as Record<string, string | undefined>;
   return {
      ...payload,
      ...input,
      id: input.event_id || input.id,
      session_id: input.conversation_id || input.session_id,
      turn_id: input.run_id || input.turn_id,
      created_at: input.timestamp || input.created_at,
      kind: input.kind || familyKind || input.legacy_type || input.type,
      action: input.action || input.title || p.action,
      target: input.target || p.target || input.related_command || input.related_files?.[0] || input.related_tool,
      path: input.path || p.path || input.related_files?.[0],
      command: input.command || p.command || input.related_command,
      tool: input.tool || p.tool || input.related_tool,
      error: errorValue || payload.error,
   };
};

export const normalizeWorkEvent = (event: WorkEvent, _artifactPathIndex: Record<string, string> = {}): WorkEvent => {
   event = adaptCanonicalWorkEvent(event);
   const kind = String(event?.kind || event?.type || '').toLowerCase();
   const action = String(event?.action || event?.title || '').toLowerCase();
   const tool = String(event?.tool || event?.name || '').toLowerCase();
   const rawTarget = String(event?.path || event?.target || '').toLowerCase();
   const role = String(event?.role || '').toLowerCase();
   const isTodoPlan = role === 'planning_artifact' || rawTarget.endsWith('todo.md');
   const normalizedKind = isTodoPlan || kind.includes('todo') ? 'todo' :
      kind.includes('approval') || action.includes('approval') ? 'approval' :
      kind.includes('retry') || action.includes('retry') ? 'retry' :
      kind.includes('error') || kind.includes('failure') ? 'error' :
      kind.includes('test') || kind.includes('diagnostic') ? 'test' :
      kind === 'artifact' ? 'file' :
      kind.includes('rag') || action.includes('rag') || action.includes('retrieval') || tool.includes('atlas') ? 'rag' :
      kind.includes('mcp') || action.includes('mcp') || tool.includes('mcp') ? 'mcp' :
      kind.includes('browser') || action.includes('browser') || tool.includes('browser') ? 'browser' :
      kind.includes('search') || kind.includes('web') || action.includes('search') || tool.includes('search') || tool.includes('grep') || tool.includes('glob') ? 'search' :
      kind.includes('command') || kind.includes('bash') || kind.includes('terminal') || kind.includes('shell') || (event as Record<string, unknown>)?.command ? 'command' :
      kind.includes('file') || action.includes('file') || tool.includes('file') || (event as Record<string, unknown>)?.path ? 'file' :
      kind.includes('skill') ? 'skill' :
      kind.includes('plugin') ? 'plugin' :
      kind.includes('provider') ? 'provider' :
      kind.includes('hive') || kind.includes('agent') || kind.includes('worker') ? 'hive' :
      kind || 'tool';
   
   const normalizedAction =
      normalizedKind === 'file' && (action.includes('delete') || action.includes('remove')) ? 'Delete file' :
      normalizedKind === 'file' && action.includes('artifact') ? 'Create file' :
      normalizedKind === 'file' && action.includes('create') ? 'Create file' :
      normalizedKind === 'file' && action.includes('write') ? 'Create file' :
      normalizedKind === 'file' && action.includes('read') ? 'Read file' :
      normalizedKind === 'file' && action.includes('view') ? 'Read file' :
      normalizedKind === 'file' && action.includes('update') ? 'Update file' :
      normalizedKind === 'file' && action.includes('edit') ? 'Edit file' :
      normalizedKind === 'search' ? 'Searching' :
      normalizedKind === 'rag' ? 'Read context' :
      normalizedKind === 'mcp' ? 'Use MCP' :
      normalizedKind === 'browser' ? 'Browse' :
      normalizedKind === 'command' ? 'Run command' :
      normalizedKind === 'approval' ? 'Approval required' :
      normalizedKind === 'retry' ? 'Retry action' :
      normalizedKind === 'error' ? 'Action failed' :
      normalizedKind === 'test' ? 'Run checks' :
      normalizedKind === 'hive' ? 'Delegate task' :
      normalizedKind === 'todo' ? 'Plan work' :
      normalizedKind === 'task' ? (action.includes('queue') ? 'Queued task' : 'Task') :
      normalizedKind === 'skill' ? 'Use skill' :
      normalizedKind === 'plugin' ? 'Use plugin' :
      normalizedKind === 'provider' ? 'Check provider' :
      normalizedKind === 'tool' ? 'Use tool' :
      event.action || String((event as Record<string, unknown>).title || '') || (normalizedKind === 'command' ? 'Run command' : 'Use tool');
   
   const inferredPhaseIndex = Number((event as Record<string, unknown>).phase_index) || undefined;
   const phase = String((event as Record<string, unknown>).phase || (event as Record<string, unknown>).phase_title || '') || undefined;
   
   return {
      ...event,
      kind: normalizedKind,
      action: normalizedAction,
      phase,
      phase_index: inferredPhaseIndex,
      target: normalizedKind === 'todo'
         ? (String((event as Record<string, unknown>).target || '') || (Array.isArray((event as Record<string, unknown>).items) ? ((event as Record<string, unknown>).items as unknown[]).map((item: unknown, index: number) => `${index + 1}. ${item}`).join('; ') : '') || String((event as Record<string, unknown>).task || ''))
         : String((event as Record<string, unknown>).target || (event as Record<string, unknown>).path || (event as Record<string, unknown>).command || (event as Record<string, unknown>).tool || (event as Record<string, unknown>).title || ''),
   };
};

export const parseWorkActivityLine = (line: string, _artifactPathIndex: Record<string, string> = {}): WorkEvent | null => {
   const trim = String(line || '').trim();
   if (!trim) return null;

   const normalizeEventLocal = (event: Record<string, unknown>, fallbackTarget = ''): WorkEvent | null => {
      if (!event || typeof event !== 'object') return null;
      const rawKind = String(event.kind || event.type || '').toLowerCase();
      const rawAction = String(event.action || event.title || '').toLowerCase();
      const rawTool = String(event.tool || event.name || '').toLowerCase();
      const target = event.target || event.path || event.command || event.query || event.tool || event.name || event.result || event.error || event.message || fallbackTarget;
      const targetText = String(target || '').toLowerCase();
      const role = String(event.role || '').toLowerCase();
      const isTodoPlan = role === 'planning_artifact' || targetText.endsWith('todo.md');
      const kind = isTodoPlan || rawKind.includes('todo') ? 'todo'
         : rawKind.includes('approval') || rawAction.includes('approval') ? 'approval'
         : rawKind.includes('retry') || rawAction.includes('retry') ? 'retry'
         : rawKind.includes('error') || rawKind.includes('failure') ? 'error'
         : rawKind.includes('test') || rawKind.includes('diagnostic') ? 'test'
         : rawKind.includes('rag') || rawAction.includes('rag') || rawAction.includes('retrieval') || rawTool.includes('atlas') ? 'rag'
         : rawKind.includes('mcp') || rawAction.includes('mcp') || rawTool.includes('mcp') ? 'mcp'
         : rawKind.includes('browser') || rawAction.includes('browser') || rawTool.includes('browser') ? 'browser'
         : rawKind.includes('search') || rawKind.includes('web') || rawAction.includes('search') || rawTool.includes('search') || rawTool.includes('grep') || rawTool.includes('glob') ? 'search'
         : rawKind.includes('command') || rawKind.includes('bash') || rawKind.includes('terminal') || rawKind.includes('shell') || event.command ? 'command'
         : rawKind.includes('file') || rawAction.includes('file') || rawTool.includes('file') || event.path ? 'file'
         : rawKind.includes('skill') ? 'skill'
         : rawKind.includes('plugin') ? 'plugin'
         : rawKind.includes('provider') ? 'provider'
         : rawKind.includes('hive') || rawKind.includes('agent') || rawKind.includes('worker') ? 'hive'
         : rawKind.includes('task') ? 'task'
         : rawKind.includes('tool') || event.tool ? 'tool'
         : 'tool';
      const action = event.action || (
         kind === 'file' ? (rawAction.includes('create') ? 'Create file' : rawAction.includes('read') ? 'Read file' : 'Edit file') :
         kind === 'search' ? 'Searching' :
         kind === 'rag' ? 'RAG' :
         kind === 'mcp' ? 'MCP' :
         kind === 'browser' ? 'Browser' :
         kind === 'command' ? 'Run command' :
         kind === 'approval' ? 'Approval required' :
         kind === 'retry' ? 'Retrying' :
         kind === 'error' ? 'Action failed' :
         kind === 'test' ? 'Run checks' :
         kind === 'skill' ? 'Skill' :
         kind === 'plugin' ? 'Plugin' :
         kind === 'provider' ? 'Provider' :
         kind === 'hive' ? 'Delegate task' :
         kind === 'todo' ? 'Todo' :
         kind === 'task' ? 'Queued task' :
         'Use tool'
      );
      return {
         ...event,
         kind: String(kind),
         action: String(action),
         target: String(target),
         status: String(event.status || (/error|fail/i.test(String(event.output || target)) ? 'error' : 'done')),
      };
   };

   const structured = trim.match(/^\[NEXUS_ACTIVITY\]:\s*(\{.*\})$/i);
   if (structured) {
      try {
         return normalizeEventLocal(JSON.parse(structured[1]) as Record<string, unknown>, trim);
      } catch {
         return null;
      }
   }

   if (trim.startsWith('{')) {
      try {
         const parsed = JSON.parse(trim) as Record<string, unknown>;
         const wrapped = parsed.event && typeof parsed.event === 'object'
            ? parsed.event as Record<string, unknown>
            : parsed;
         return normalizeEventLocal(wrapped, trim);
      } catch {
         return null;
      }
   }

   return null;
};

/** Merge lifecycle updates by backend identity without hiding separate actions. */
export const collapseWorkActivityUpdates = (rows: WorkEvent[]): WorkEvent[] => {
   const collapsed: WorkEvent[] = [];
   const indexById = new Map<string, number>();

   rows.forEach(row => {
      const id = String(row.event_id || row.id || '').trim();
      if (!id) {
         collapsed.push(row);
         return;
      }
      const existingIndex = indexById.get(id);
      if (existingIndex === undefined) {
         indexById.set(id, collapsed.length);
         collapsed.push(row);
         return;
      }
      const existing = collapsed[existingIndex];
      const incomingSequence = Number(row.sequence || 0);
      const existingSequence = Number(existing.sequence || 0);
      if (!incomingSequence || !existingSequence || incomingSequence >= existingSequence) {
         collapsed[existingIndex] = { ...existing, ...row };
      }
   });

   return collapsed;
};

export const MAX_LIVE_WORK_EVENTS = 500;
export const MAX_LIVE_OUTPUT_CHARS = 256 * 1024;

/** Retain the newest output without letting a long-running command exhaust browser memory. */
export const boundedLiveOutput = (value: string, limit = MAX_LIVE_OUTPUT_CHARS): string => {
   const text = String(value || '');
   if (text.length <= limit) return text;
   const marker = `[... earlier output omitted ...]\n`;
   if (limit <= marker.length) return text.slice(-Math.max(0, limit));
   return `${marker}${text.slice(-(limit - marker.length))}`;
};

/**
 * Merge event lifecycle updates in one pass, preserve first-seen order, and
 * bound the in-memory live timeline. Persisted history remains available from
 * the API; this limit only protects the active browser tab.
 */
export const mergeLiveWorkEvents = (
   current: WorkEvent[],
   incoming: WorkEvent[],
   limit = MAX_LIVE_WORK_EVENTS,
): WorkEvent[] => {
   const merged = collapseWorkActivityUpdates([...current, ...incoming]);
   return merged.length > limit ? merged.slice(-limit) : merged;
};

/** Keep user-facing work evidence; suppress routine orchestration telemetry. */
export const isDisplayableWorkActivity = (row: WorkEvent): boolean => {
   const kind = String(row.kind || row.type || '').toLowerCase();
   const action = String(row.action || row.title || '').toLowerCase();
   const target = String(row.target || row.path || '').trim().toLowerCase();
   const stage = String(row.stage || '').toLowerCase();
   const status = String(row.status || '').toLowerCase();
   const source = String(row.source || '').trim().toLowerCase();
   const semanticText = [row.action, row.title, row.target, row.path, row.source, row.result]
      .map(value => String(value || '').toLowerCase())
      .join(' ');
   const failed = ['error', 'failed', 'failure', 'blocked', 'aborted'].includes(status)
      || Boolean(row.error || row.stderr || row.preview_error);

   if (String(row.visibility || '').toLowerCase() === 'internal') return false;
   const internalBootstrapTarget = [
      'prompt_files', 'stable', 'rules', 'permissions', 'workstyle',
      'project_docs', 'knowledge', 'memory', 'context pack',
   ].includes(target) || [
      'prompt_files', 'stable', 'rules', 'permissions', 'workstyle',
      'project_docs', 'knowledge', 'memory', 'context pack',
   ].includes(source);
   const internalDiagnostic = semanticText.includes('critical preventive vaccine')
      || semanticText.includes('verification found a problem');
   if (stage === 'grounding' || internalBootstrapTarget || internalDiagnostic) return false;
   if (failed) return true;

   // The public workspace is an allowlist of user-meaningful evidence. Any
   // orchestration event not explicitly classified here stays internal.
   if (stage === 'planning') return true;

   // Calling the selected model is required for every reply, but it is not a
   // separate user task. Surface it only when something went wrong.
   if (kind === 'provider') return false;

   // Stable prompt, rules, permissions, workstyle and prompt files are
   // internal model bootstrap context. They are not work performed for the
   // user's request and must never become timeline bubbles.
   if (['grounding', 'inference', 'plan', 'auditing', 'execution', 'verification', 'memory', 'finalize'].includes(stage)) return false;

   // Defensive fallback for older persisted events that predate the `stage`
   // field but still use an internal session id as their only target.
   if (kind === 'task' && /^session_[a-z0-9_-]+$/i.test(target)) return false;

   // These are transport/dispatch records, not work performed on the task.
   if (kind === 'task' && action.includes('queue') && !row.result && !row.output && !row.tool_calls) return false;

   // A generic context marker explains nothing. Named context with actual
   // evidence remains visible (rules, memory, code, project docs, etc.).
   if (kind === 'rag' || kind === 'task' || kind === 'provider') return false;

   if (['file', 'command', 'search', 'browser', 'mcp', 'skill', 'plugin', 'hive', 'todo', 'approval', 'retry', 'error'].includes(kind)) return true;

   if (kind === 'test') {
      return /\b(test|build|lint|compile|diagnostic)\b/.test(`${action} ${target}`)
         && !/\b(verif|check result|accepted)\b/.test(`${action} ${target}`);
   }

   if (kind === 'tool') {
      const toolName = String(row.tool || row.name || '').trim().toLowerCase();
      const internalTarget = ['tool safety audit', 'agent tools', 'execution', 'latest tool results', 'checks', 'tool results accepted'].includes(target);
      const internalAction = /proposed tool|queued \d+ tool|observations received|approved tools/.test(action);
      return Boolean(toolName) && !internalTarget && !internalAction;
   }

   return false;
};
