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

console.log('startup session behavior: ok');
