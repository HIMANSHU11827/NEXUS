import {readFileSync} from 'node:fs';
import path from 'node:path';

const appPath = path.join(import.meta.dirname, 'nexus-tui.tsx');
// Normalize CRLF (Windows checkouts) so multi-line fragment matching is
// platform-independent.
const source = readFileSync(appPath, 'utf8').replace(/\r\n/g, '\n');

const requiredFragments = [
    'activeRunIdRef',
    'const cancelActiveTurn = () =>',
    '/chat/${encodeURIComponent(sessionId)}/cancel${suffix}',
    'headers: API_AUTH_HEADERS',
    "if (key.escape && isThinking) {\n            cancelActiveTurn();",
    "if (command === '/stop') {",
    'const observedRunId = event.run_id || event.turn_id',
    'const queuedQuestionAnswerRef = useRef(new QuestionAnswerQueue());',
    'const queuedAnswer = queuedQuestionAnswerRef.current.take()',
    'queuedQuestionAnswerRef.current.enqueue(submission.answer);',
    'setTimeout(() => { void handleSubmit(queuedAnswer); }, 0);',
];

for (const fragment of requiredFragments) {
    if (!source.includes(fragment)) throw new Error(`missing TUI cancellation contract: ${fragment}`);
}

if (!source.includes('turnInFlightRef.current = false;\n                const queuedAnswer = queuedQuestionAnswerRef.current.take()')) {
    throw new Error('queued question answers must flush only after the active turn lock is released');
}

console.log('TUI cancellation contract: ok');
