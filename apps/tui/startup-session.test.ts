import {readFileSync} from 'node:fs';

const source = readFileSync('nexus-tui.tsx', 'utf8');

if (source.includes("apiJson('/sessions/active')") || source.includes('apiJson("/sessions/active")')) {
    throw new Error('startup must not auto-load the active persisted session');
}

if (!source.includes('INITIAL_HISTORY')) {
    throw new Error('startup should render an empty initial history');
}

if (!source.includes("useState(() => `tui_${Date.now()}`)")) {
    throw new Error('startup should use a fresh local session id before the API is ready');
}

if (!source.includes('const apiReady = await ensureApiAvailable()')) {
    throw new Error('startup should wait for the API before creating a session');
}

if (!source.includes('NEXUS_EMBED_QUEUE_DRIVER')) {
    throw new Error('direct TUI startup should launch a queue-enabled API by default');
}

if (!source.includes('NEXUS_DASHBOARD_TOKEN: DASHBOARD_TOKEN')) {
    throw new Error('direct TUI startup must pass the client token to the embedded API');
}

if ((source.match(/startDetached\(PYTHON_EXECUTABLE/g) || []).length < 2) {
    throw new Error('direct TUI startup must use the repository virtualenv Python when available');
}

console.log('startup session behavior: ok');
