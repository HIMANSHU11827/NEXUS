import React from 'react';
import assert from 'node:assert/strict';
import {Box} from 'ink';
import {ApprovalPanelBody} from './details-panel.js';
import {approvalFromWorkEvent} from './helpers.js';
import {approvalDecisionFromInput} from './approval-state.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

const approval = approvalFromWorkEvent({
    id: 'approval-1',
    event_type: 'tool.approval_request',
    kind: 'approval',
    status: 'running',
    request_id: 'approval-1',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool: 'terminal',
    action: 'rm build/cache',
    reason: 'This command changes files in the workspace.',
    expires_at: 123456
});

assert.deepEqual(approval, {
    id: 'approval-1',
    requestId: 'approval-1',
    tool: 'terminal',
    action: 'rm build/cache',
    reason: 'This command changes files in the workspace.',
    sessionId: 'session-1',
    turnId: 'turn-1',
    expiresAt: 123456
});

assert.deepEqual(approvalFromWorkEvent({
    event_type: 'approval.requested',
    payload: {
        id: 'approval-2',
        status: 'pending',
        tool: 'write_file',
        target: 'README.md',
        reason: 'A workspace file will be modified.'
    }
}), {
    id: 'approval-2',
    requestId: 'approval-2',
    tool: 'write_file',
    action: 'README.md',
    reason: 'A workspace file will be modified.',
    sessionId: undefined,
    turnId: undefined,
    expiresAt: undefined
});

assert.equal(approvalFromWorkEvent({kind: 'tool', status: 'running', tool: 'terminal', action: 'ls'}), null);
assert.equal(approvalFromWorkEvent({kind: 'approval', status: 'done', tool: 'terminal', action: 'ls', id: 'approval-3'}), null);
assert.equal(approvalDecisionFromInput('y'), 'allow');
assert.equal(approvalDecisionFromInput('a'), 'allow_always');
assert.equal(approvalDecisionFromInput('n'), 'deny');
assert.equal(approvalDecisionFromInput('', true), 'deny');

const frame = await renderInkFrame(
    <Box width={52} height={22} flexDirection="column">
        <ApprovalPanelBody approval={approval} width={52} />
    </Box>,
    52,
    22
);
const plain = stripAnsi(frame).replace(/\r/g, '');
assert.match(plain, /APPROVAL REQUIRED/);
assert.match(plain, /Approve terminal\?/);
assert.match(plain, /terminal/);
assert.match(plain, /rm build\/cache/);
assert.match(plain, /This command changes files/);
assert.match(plain, /y\/1 allow.*a\/2 always.*n\/3 or Esc deny/);
assert.ok(plain.split('\n').every(line => [...line].length <= 52), 'approval panel fits its inspector width');

console.log('Approval helper and panel tests passed');
