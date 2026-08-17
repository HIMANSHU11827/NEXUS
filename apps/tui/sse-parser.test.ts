import {readFileSync} from 'node:fs';

const source = readFileSync('nexus-tui.tsx', 'utf8');

if (!source.includes('const payload = JSON.parse(raw);') || !source.includes('payload.content ?? payload.data ?? raw')) {
    throw new Error('message SSE frames must unwrap JSON content before rendering');
}

const doneIndex = source.indexOf("if (eventType === 'done')");
const payloadIndex = source.indexOf('let payload: any;');
if (doneIndex < 0 || payloadIndex < 0 || doneIndex > payloadIndex) {
    throw new Error('done SSE frames must be handled before generic JSON parsing');
}

console.log('chat SSE parser behavior: ok');
