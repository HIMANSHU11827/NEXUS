import {readFileSync} from 'node:fs';
import path from 'node:path';

const appPath = path.join(import.meta.dirname, 'nexus-tui.tsx');
const source = readFileSync(appPath, 'utf8');

const requiredFragments = [
    'activeRunIdRef',
    'const cancelActiveTurn = () =>',
    '/chat/${encodeURIComponent(sessionId)}/cancel${suffix}',
    'headers: API_AUTH_HEADERS',
    "if (key.escape && isThinking) {\n            cancelActiveTurn();",
    "if (command === '/stop') {",
    'const observedRunId = event.run_id || event.turn_id',
];

for (const fragment of requiredFragments) {
    if (!source.includes(fragment)) throw new Error(`missing TUI cancellation contract: ${fragment}`);
}

console.log('TUI cancellation contract: ok');
