#!/usr/bin/env node
/**
 * NEXUS Headless TUI — run from any device (laptop, mobile, tablet, TV).
 * Usage: tsx nexus-tui-headless.ts <command> [args]
 *        npx tsx nexus-tui-headless.ts status
 *        npx tsx nexus-tui-headless.ts chat "build the feature"
 */
const configuredApi = process.env.NEXUS_API?.trim();
const configuredHost = process.env.NEXUS_API_HOST?.trim() || '127.0.0.1';
const configuredPort = process.env.NEXUS_API_PORT?.trim() || '8000';
let API_BASE = configuredApi
  ? configuredApi.replace(/\/$/, '')
  : `http://${configuredHost}:${configuredPort}/api`;
const DASHBOARD_TOKEN = process.env.NEXUS_DASHBOARD_TOKEN?.trim();
const API_HEADERS: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${DASHBOARD_TOKEN || 'nexus-local-tui'}`
};
const PUBLIC_ACTIVITY_KINDS = new Set([
    'plan', 'todo', 'tool', 'command', 'file', 'test', 'search', 'browser',
    'mcp', 'skill', 'plugin', 'hive', 'agent', 'worker', 'provider', 'rag',
    'approval', 'error', 'retry'
]);

function adaptCanonicalEvent(input: Record<string, any>): Record<string, any> {
    const payload = input.payload && typeof input.payload === 'object' ? input.payload : {};
    const eventType = String(input.event_type || input.type || '').toLowerCase();
    const family = eventType.includes('.') ? eventType.split('.')[0] : '';
    const kind = family === 'web' ? 'search'
        : ['subagent', 'handoff'].includes(family) ? 'hive'
        : ['plan', 'phase'].includes(family) ? 'plan'
        : ['run', 'conversation', 'message', 'status'].includes(family) ? 'agent'
        : family;
    const error = input.error && typeof input.error === 'object' ? input.error.message : input.error;
    return {
        ...payload, ...input,
        id: input.event_id || input.id,
        kind: input.kind || kind || input.legacy_type || input.type,
        action: input.action || input.title || payload.action,
        target: input.target || payload.target || input.related_command || input.related_files?.[0] || input.related_tool,
        command: input.command || payload.command || input.related_command,
        tool: input.tool || payload.tool || input.related_tool,
        error: error || payload.error
    };
}

function visibleChatContent(value: unknown): string {
    return String(value || '')
        .replace(/^\s*>\s*⚡\s*\*\*\[(grounding|inference|auditing|verifying|done)\]\*\*\s*$/gim, '')
        .replace(/^\s*\[(grounding|inference|auditing|verifying|done)\]\s*$/gim, '')
        .replace(/\n{3,}/g, '\n\n');
}

async function apiJson(endpoint: string, init?: RequestInit) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...init,
        headers: {
            ...API_HEADERS,
            ...(init?.headers || {})
        }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = data.detail || data.error || response.statusText;
        console.error(String(detail));
        process.exit(1);
    }
    return data;
}

async function postJson(endpoint: string, body: Record<string, any>) {
    return apiJson(endpoint, {
        method: 'POST',
        body: JSON.stringify(body)
    });
}

async function cmdStatus() {
    const status = await apiJson('/status');
    console.log(JSON.stringify(status, null, 2));
}

async function cmdMode() {
    const mode = await apiJson('/mode');
    console.log(JSON.stringify(mode, null, 2));
}

async function cmdProviders() {
    const data = await apiJson('/providers');
    console.log(JSON.stringify(data, null, 2));
}

async function cmdProvider(args: string[]) {
    const action = args[0]?.toLowerCase();
    const id = args[1];
    if (action === 'open' && id) {
        const data = await apiJson(`/provider/${id}`);
        console.log(JSON.stringify(data, null, 2));
    } else if (action === 'add') {
        const name = args.slice(1).join(' ');
        const data = await postJson('/provider', { name });
        console.log(JSON.stringify(data, null, 2));
    } else if (action === 'enable' && id) {
        const data = await postJson(`/provider/${id}`, { active: true });
        console.log(JSON.stringify(data, null, 2));
    } else if (action === 'disable' && id) {
        const data = await postJson(`/provider/${id}`, { active: false });
        console.log(JSON.stringify(data, null, 2));
    } else if (action === 'model' && id && args[2]) {
        const data = await postJson(`/provider/${id}`, { model: args[2] });
        console.log(JSON.stringify(data, null, 2));
    } else {
        console.log(`Usage: provider <action> [args]
Actions:
  open <id>       Show provider detail
  add <name>      Add new provider
  enable <id>     Enable provider
  disable <id>    Disable provider
  model <id> <m>  Set model`);
    }
}

async function cmdVoice(args: string[]) {
    const action = (args[0] || 'status').toLowerCase();
    if (action === 'on' || action === 'start') {
        const data = await postJson('/voice/start', { mode: 'auto' });
        console.log(JSON.stringify(data, null, 2));
    } else if (action === 'off' || action === 'stop') {
        const data = await postJson('/voice/stop', {});
        console.log(JSON.stringify(data, null, 2));
    } else {
        const data = await apiJson('/voice/status').catch(() => ({ running: false }));
        console.log(JSON.stringify(data, null, 2));
    }
}

async function cmdEvents(args: string[]) {
    const limit = parseInt(args[0], 10) || 20;
    const session = args[1] || 'default';
    const data = await apiJson(`/work-events?session_id=${encodeURIComponent(session)}&limit=${limit}`);
    console.log(JSON.stringify(data, null, 2));
}

async function cmdChat(args: string[]) {
    const prompt = args.join(' ');
    if (!prompt) {
        console.error('Usage: chat <prompt>');
        process.exit(1);
    }
    const response = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: API_HEADERS,
        body: JSON.stringify({
            prompt,
            session_id: null,
            provider: null,
            model: null,
            stream: true,
            canonical_events: true
        })
    });
    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        console.error(err.detail || err.error || response.statusText);
        process.exit(1);
    }
    if (!response.body) {
        console.error('No response body');
        process.exit(1);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const activityStatus = new Map<string, string>();
    const toolPrinted = new Set<string>();
    let failed = false;

    const renderToolLine = (id: string, status: string, action: string, target: string, evidence: string) => {
        if (toolPrinted.has(id)) return;
        if (status === 'queued' || status === 'pending' || status === 'running') return;
        toolPrinted.add(id);
        const line = `[${status}] ${action}${target}${evidence ? ` · ${evidence}` : ''}`;
        process.stderr.write(line + '\n');
    };

    const consumeFrame = (frame: string) => {
        const eventType = frame.split(/\r?\n/)
            .find(line => line.startsWith('event:'))?.slice(6).trim() || 'message';
        const payloadText = frame.split(/\r?\n/)
            .filter(line => line.startsWith('data:'))
            .map(line => line.replace(/^data:\s?/, ''))
            .join('\n');
        if (!payloadText || eventType === 'heartbeat') return;
        if (eventType === 'message') {
            process.stdout.write(visibleChatContent(payloadText));
            return;
        }
        if (eventType === 'error') {
            console.error(payloadText);
            failed = true;
            return;
        }
        let payload: any;
        try {
            payload = JSON.parse(payloadText);
        } catch {
            if (payloadText.trim() === '[DONE]') return;
            console.error(`Malformed server event (${eventType})`);
            failed = true;
            return;
        }
        if (eventType === 'work_event' || eventType === 'nexus.event') {
            const event = adaptCanonicalEvent(payload.event || payload);
            const kind = String(event.kind || event.type || '').toLowerCase();
            if (event.visibility !== 'public' || !PUBLIC_ACTIVITY_KINDS.has(kind)) return;

            const id = String(event.id || `${event.kind || 'work'}:${event.action || ''}`);
            const status = String(event.status || 'running');
            if (activityStatus.get(id) === status) return;
            activityStatus.set(id, status);
            const action = event.action || event.label || event.kind || 'Agent activity';
            const target = event.target ? ` · ${event.target}` : '';
            const evidence = [
                event.duration_ms != null ? `${event.duration_ms} ms` : '',
                event.exit_code != null ? `exit ${event.exit_code}` : '',
                event.changed_lines || event.line_changes ? `lines ${JSON.stringify(event.changed_lines || event.line_changes)}` : '',
                event.error ? `error ${String(event.error)}` : ''
            ].filter(Boolean).join(' · ');
            const isToolEvent = ['tool', 'command', 'file', 'search', 'browser', 'test', 'mcp', 'skill', 'plugin', 'hive'].includes(kind);
            if (isToolEvent) {
                renderToolLine(id, status, action, target, evidence);
            } else {
                process.stderr.write(`[${status}] ${action}${target}${evidence ? ` · ${evidence}` : ''}\n`);
            }
            if (['error', 'failed', 'blocked', 'aborted', 'cancelled'].includes(status.toLowerCase())) failed = true;
            return;
        }
        if (payload.content) process.stdout.write(visibleChatContent(payload.content));
    };

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        frames.forEach(consumeFrame);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consumeFrame(buffer);
    if (failed) process.exitCode = 1;
}

async function cmdSandbox(args: string[]) {
    const sub = args[0]?.toLowerCase();
    if (!sub || sub === 'status') {
        try {
            const data = await apiJson('/sandbox');
            console.log(JSON.stringify(data, null, 2));
        } catch {
            console.log(JSON.stringify({ tier: 'no_sandbox', available: [] }, null, 2));
        }
    } else if (sub === 'off' || sub === 'none') {
        const result = await postJson('/sandbox', { tier: 'no_sandbox' });
        console.log(JSON.stringify(result, null, 2));
    } else if (sub === 'normal' || sub === 'simple' || sub === 'docker') {
        const result = await postJson('/sandbox', { tier: sub === 'simple' ? 'normal' : sub });
        console.log(JSON.stringify(result, null, 2));
    } else {
        const result = await postJson('/sandbox', { tier: sub });
        console.log(JSON.stringify(result, null, 2));
    }
}

async function cmdDeepResearch(args: string[]) {
    const query = args.join(' ') || 'deep research on current project';
    console.error(`Deep research: ${query.slice(0, 80)}...`);
    const data = await postJson('/multi_agent', { prompt: query, mode: 'research' });
    console.log(JSON.stringify(data, null, 2));
}

async function cmdUltraplan(args: string[]) {
    const query = args.join(' ') || 'draft a high-effort plan';
    console.error(`Ultraplan: ${query.slice(0, 80)}...`);
    const data = await postJson('/multi_agent', { prompt: query, mode: 'plan' });
    console.log(JSON.stringify(data, null, 2));
}

async function cmdHealth() {
    const data = await apiJson('/health');
    console.log(JSON.stringify(data, null, 2));
}

async function cmdSessions() {
    const data = await apiJson('/sessions/active');
    console.log(JSON.stringify(data, null, 2));
}

async function cmdTerminal(args: string[]) {
    const command = args.join(' ');
    if (!command) {
        console.error('Usage: exec <shell command>');
        process.exit(1);
    }
    console.error(`[running] ${command}`);
    const response = await fetch(`${API_BASE}/work-events/run-command-stream`, {
        method: 'POST',
        headers: API_HEADERS,
        body: JSON.stringify({command, session_id: 'headless-tui'})
    });
    if (!response.ok || !response.body) {
        console.error(await response.text().catch(() => response.statusText));
        process.exitCode = 1;
        return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    const consume = (frame: string) => {
        const raw = frame.split(/\r?\n/).filter(line => line.startsWith('data:'))
            .map(line => line.replace(/^data:\s?/, '')).join('\n');
        if (!raw) return;
        let event: any;
        try {
            event = JSON.parse(raw);
        } catch {
            console.error('Malformed command stream event');
            process.exitCode = 1;
            return;
        }
        if (event.type === 'chunk') {
            (event.stream === 'stderr' ? process.stderr : process.stdout).write(String(event.text || ''));
        } else if (event.type === 'done') {
            const exitCode = Number(event.exit_code ?? (event.status === 'done' ? 0 : 1));
            console.error(`[${exitCode === 0 ? 'done' : 'error'}] exit code ${exitCode}`);
            process.exitCode = exitCode;
        }
    };
    while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const frames = buffer.split(/\r?\n\r?\n/);
        buffer = frames.pop() || '';
        frames.forEach(consume);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
}

function printHelp() {
    console.log(`Usage: tsx nexus-cli-headless.ts <command> [args]
Commands:
  status               Server status
  mode                 Current provider & mode
  providers            List providers
  provider <action>    Provider management (open, add, enable, disable, model)
  voice [on|off]       Voice mode control
  events [n] [sess]    Work events
  chat <prompt>        Send chat prompt
  sandbox [tier]       Sandbox control
  research <query>     Deep research
  plan <query>         Ultraplan
  exec <cmd>           Run any shell command
  health               Health check
  sessions             Active sessions
  --api <url>          Set API base (default: http://localhost:8000/api)
  --help               This help`);
}

async function main() {
    const argv = process.argv.slice(2);
    if (argv[0] === '--api') {
        if (!argv[1]) {
            console.error('Usage: --api <url>');
            process.exit(1);
        }
        API_BASE = argv[1].replace(/\/$/, '');
        argv.splice(0, 2);
    }

    const command = argv[0]?.toLowerCase();
    const args = argv.slice(1);

    switch (command) {
        case undefined:
        case '--help':
        case '-h':        printHelp(); break;
        case 'status':    await cmdStatus(); break;
        case 'mode':      await cmdMode(); break;
        case 'providers': await cmdProviders(); break;
        case 'provider':  await cmdProvider(args); break;
        case 'voice':     await cmdVoice(args); break;
        case 'events':    await cmdEvents(args); break;
        case 'chat':      await cmdChat(args); break;
        case 'sandbox':   await cmdSandbox(args); break;
        case 'research':
        case 'deep-research': await cmdDeepResearch(args); break;
        case 'plan':
        case 'ultraplan': await cmdUltraplan(args); break;
        case 'health':    await cmdHealth(); break;
        case 'sessions':  await cmdSessions(); break;
        case 'exec':
        case 'terminal':
        case 'run':       await cmdTerminal(args); break;
        default:
            printHelp();
            process.exit(1);
    }
}

main().catch(err => {
    console.error(err.message);
    process.exit(1);
});
