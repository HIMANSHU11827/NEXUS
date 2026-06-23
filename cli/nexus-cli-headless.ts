#!/usr/bin/env node
/**
 * NEXUS Headless CLI — run from any device (laptop, mobile, tablet, TV).
 * Usage: tsx nexus-cli-headless.ts <command> [args]
 *        npx tsx nexus-cli-headless.ts status
 *        npx tsx nexus-cli-headless.ts chat "build the feature"
 */
const API_BASE = process.env.NEXUS_API || "http://localhost:8000/api";

async function apiJson(endpoint: string, init?: RequestInit) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
        ...init,
        headers: {
            'Content-Type': 'application/json',
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
    const data = await apiJson(`/work/events?session_id=${session}&limit=${limit}`);
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
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, session_id: null, provider: null, model: null })
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
    let text = '';
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    console.log(text);
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
    } else if (sub === 'normal' || sub === 'docker') {
        const result = await postJson('/sandbox', { tier: sub });
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
    const data = await postJson('/terminal/execute', { command });
    if (data.stdout) process.stdout.write(data.stdout);
    if (data.stderr) process.stderr.write(data.stderr);
    if (data.exit_code !== undefined) process.exit(data.exit_code);
    if (data.error) console.error(data.error);
}

async function main() {
    const command = process.argv[2]?.toLowerCase();
    const args = process.argv.slice(3);

    switch (command) {
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
            console.error(`Usage: tsx nexus-cli-headless.ts <command> [args]
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
            process.exit(1);
    }
}

main().catch(err => {
    console.error(err.message);
    process.exit(1);
});
