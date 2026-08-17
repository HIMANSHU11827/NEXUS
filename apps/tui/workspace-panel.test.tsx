import React from 'react';
import assert from 'node:assert/strict';
import {NexusWorkspacePanel} from './workspace-panel.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

const frame = await renderInkFrame(
    <NexusWorkspacePanel
        timeline={[]}
        usage={{contextTokens: 0, contextLimit: 0, inputTokens: 0, outputTokens: 0, source: 'unavailable'}}
        mode="workspace"
        agents={[]}
        tasks={[]}
        touchedFiles={[
            {name: 'src/new.ts', status: 'CREATE FILE'},
            {name: 'src/app.ts', status: 'EDIT FILE', additions: 4, deletions: 2},
            {name: 'src/partial.ts', status: 'EDIT FILE', additions: 3}
        ]}
        activityItems={[]}
        pendingQuestion={null}
        selectedQuestionIndex={0}
        planItems={[]}
        planStatus="planning"
        planExpanded={false}
        mcpConnectedCount={0}
        mcpServers={[]}
        selectedActivityId={null}
        selectedAgentId={null}
        motionFrame={0}
        voiceMode="off"
        voicePhase="off"
        voiceTranscriptPreview=""
        voiceReplyPreview=""
        width={80}
        height={30}
        currentTask="Editing files"
        isWorking={false}
        workingPhase="thinking"
        elapsedMs={0}
    />,
    80,
    30
);
const plain = stripAnsi(frame).replace(/\r/g, '');
assert.match(plain, /WORKSPACE/);
assert.doesNotMatch(plain, /Editing files/);
assert.match(plain, /CONTEXT/);
const lines = plain.split('\n');
const workspaceRow = lines.findIndex(line => line.includes('WORKSPACE'));
const contextRow = lines.findIndex(line => line.includes('CONTEXT'));
assert.ok(workspaceRow >= 0 && contextRow > workspaceRow && contextRow - workspaceRow <= 5, 'no redundant gap before CONTEXT');
assert.match(plain, /CHANGES/);
assert.match(plain, /new\.ts/);
assert.match(plain, /app\.ts/);
assert.match(plain, /partial\.ts/);
assert.match(plain, /\+4\s+-2/);
assert.match(plain, /\+3/);
assert.doesNotMatch(plain, /\+0|-0/);
assert.doesNotMatch(plain, /readme\.md/);
assert.match(plain, /3 files changed/);

console.log('Workspace changes panel tests passed');
