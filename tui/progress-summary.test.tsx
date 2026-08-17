import React from 'react';
import assert from 'node:assert/strict';
import {Box} from 'ink';
import {ChatLineView, buildChatLines} from './chat-view.js';
import {
    progressSummaryFromWorkEvent,
    progressSummaryText,
    type ActivityItem,
    type Message
} from './helpers.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

const progress = progressSummaryFromWorkEvent({
    event_id: 'progress-safe-1',
    event_type: 'assistant.progress',
    visibility: 'public',
    status: 'running',
    payload: {
        projection: 'deterministic-v1',
        current_action: 'The file read failed. I am selecting a corrected path.',
        evidence: 'reading returned path not found',
        retry_reason: 'the requested path does not exist',
        next_action: 'retry_with_corrected_path',
        tool: 'reading',
        reasoning: 'PRIVATE_REASONING_MUST_NOT_RENDER',
        chain_of_thought: 'PRIVATE_CHAIN_MUST_NOT_RENDER',
        arguments: {token: 'SECRET_ARGUMENT_MUST_NOT_RENDER'}
    }
});
assert.ok(progress);
assert.equal(progress.currentAction, 'The file read failed. I am selecting a corrected path.');
assert.equal(progress.evidence, 'reading returned path not found');
assert.equal(progress.retryReason, 'the requested path does not exist');
assert.equal(progress.nextAction, 'retry_with_corrected_path');
const safeText = progressSummaryText(progress);
assert.match(safeText, /evidence: reading returned path not found/);
assert.match(safeText, /retry: the requested path does not exist/);
assert.match(safeText, /next: retry with corrected path/);
assert.doesNotMatch(safeText, /PRIVATE_|SECRET_ARGUMENT/);

const scrubbed = progressSummaryFromWorkEvent({
    event_type: 'assistant.progress',
    visibility: 'public',
    payload: {
        projection: 'deterministic-v1',
        current_action: '<think>DO NOT SHOW THIS</think>Running the focused tests.\u001b[31m',
        next_action: 'verify'
    }
});
assert.ok(scrubbed);
assert.equal(scrubbed.currentAction, 'Running the focused tests.');
assert.doesNotMatch(progressSummaryText(scrubbed), /DO NOT SHOW|\u001b/);

assert.equal(progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'internal', payload: {note: 'internal'}
}), null);
assert.equal(progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'public', payload: {
        projection: 'deterministic-v1', current_action: 'Reasoning: private scratchpad'
    }
}), null);
assert.equal(progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'public', payload: {
        projection: 'deterministic-v1', current_action: '<think>unfinished private scratchpad'
    }
}), null);
assert.equal(progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'public', payload: {
        current_action: 'Untrusted provider progress'
    }
}), null);
assert.equal(progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'public', title: 'Fallback title', action: 'Fallback action',
    payload: {projection: 'deterministic-v1', note: 'Fallback note', text: 'Fallback text'}
}), null);
assert.equal(progressSummaryFromWorkEvent({
    event_type: 'tool.started', visibility: 'public', payload: {note: 'not progress'}
}), null);

const tool: ActivityItem = {
    id: 'tool-1', number: 1, kind: 'file', title: 'Read file', summary: 'src/app.ts',
    status: 'done', toolName: 'reading', files: ['src/app.ts']
};
const after = progressSummaryFromWorkEvent({
    event_id: 'progress-safe-2',
    event_type: 'assistant.progress',
    visibility: 'public',
    payload: {
        projection: 'deterministic-v1', current_action: 'The file read completed.',
        evidence: 'src/app.ts loaded', next_action: 'continue'
    }
});
assert.ok(after);

const history: Message[] = [
    {role: 'user', content: 'Inspect the app'},
    {role: 'progress', content: progressSummaryText(progress), progress},
    {role: 'activity', content: tool.title, activityId: tool.id},
    {role: 'progress', content: progressSummaryText(after), progress: after},
    {role: 'assistant', content: 'Inspection complete.'}
];
const lines = buildChatLines(history, [tool], 100, null, null, false);
const beforeIndex = lines.findIndex(line => line.key.startsWith('progress-1'));
const toolIndex = lines.findIndex(line => line.activity?.id === tool.id);
const afterIndex = lines.findIndex(line => line.key.startsWith('progress-3'));
const answerIndex = lines.findIndex(line => line.surface === 'assistant');
assert.ok(beforeIndex >= 0 && beforeIndex < toolIndex);
assert.ok(toolIndex < afterIndex && afterIndex < answerIndex);

const frame = stripAnsi(await renderInkFrame(
    <Box width={100} flexDirection="column">
        {lines.map(line => <ChatLineView key={line.key} line={line} width={100} frame={1} />)}
    </Box>,
    100,
    20
));
assert.match(frame, /Update > The file read failed/);
assert.match(frame, /reading.*app\.ts/i);
assert.match(frame, /Update > The file read completed/);
assert.match(frame, /Nexus > Inspection complete\./);
assert.doesNotMatch(frame, /PRIVATE_|SECRET_ARGUMENT|DO NOT SHOW/);

console.log('Safe assistant progress projection and render tests passed');
