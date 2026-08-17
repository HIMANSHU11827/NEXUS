import React from 'react';
import assert from 'node:assert/strict';
import {NexusWorkspacePanel} from './workspace-panel.js';
import {
    finalizePlanChecklist,
    mergePlanChecklistEvent,
    mergePlanChecklistTasks,
    mergeProgressIntoPlanChecklist,
    planChecklistStatus,
    progressSummaryFromWorkEvent
} from './helpers.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

let plan = mergePlanChecklistEvent([], {
    event_id: 'plan-1',
    event_type: 'plan.updated',
    kind: 'plan',
    status: 'pending',
    visibility: 'public',
    payload: {
        plan_id: 'plan-safe',
        steps: [
            {index: 1, step_id: 'inspect', description: 'Inspect current rendering', status: 'running'},
            {index: 2, step_id: 'implement', description: 'Implement progress rows', status: 'pending'},
            {index: 3, step_id: 'verify', description: 'Run TUI tests', status: 'pending'}
        ]
    }
});
assert.deepEqual(plan.map(item => [item.id, item.index, item.status]), [
    ['inspect', 1, 'running'],
    ['implement', 2, 'pending'],
    ['verify', 3, 'pending']
]);
assert.equal(planChecklistStatus(plan), 'running');

plan = mergePlanChecklistEvent(plan, {
    event_type: 'plan.step.completed', kind: 'plan', status: 'success',
    payload: {plan_id: 'plan-safe', step_id: 'inspect', step_index: 1, description: 'Inspect current rendering'}
});
assert.equal(plan[0].status, 'done');
assert.equal(plan[1].status, 'pending');

const progress = progressSummaryFromWorkEvent({
    event_type: 'assistant.progress', visibility: 'public',
    payload: {
        projection: 'deterministic-v1',
        current_action: 'The implementation failed one focused assertion.',
        evidence: 'expected one progress row',
        retry_reason: 'the fixture used an outdated role',
        next_action: 'update_fixture',
        outcome: 'failed',
        plan_id: 'plan-safe',
        step_id: 'implement',
        step_index: 2
    }
});
assert.ok(progress);
plan = mergeProgressIntoPlanChecklist(plan, progress);
assert.equal(plan[1].status, 'failed');
assert.equal(plan[1].evidence, 'expected one progress row');
assert.equal(plan[1].retryReason, 'the fixture used an outdated role');

plan = mergePlanChecklistTasks(plan, [
    {id: 'task-verify', subject: 'Run TUI tests', status: 'running', startedAt: 3000},
    {id: 'task-inspect', subject: 'Inspect current rendering', status: 'completed', startedAt: 1000},
    {id: 'task-implement', subject: 'Implement progress rows', status: 'failed', startedAt: 2000}
]);
assert.deepEqual(plan.map(item => item.description), [
    'Inspect current rendering', 'Implement progress rows', 'Run TUI tests'
]);
assert.deepEqual(plan.map(item => item.status), ['done', 'failed', 'running']);
assert.equal(planChecklistStatus(plan), 'running');

const activePlanOverlay = mergePlanChecklistTasks(plan, [
    {id: 'unrelated-old-task', subject: 'Do not append stale task', status: 'running'}
], false);
assert.equal(activePlanOverlay.length, 3);

const terminal = finalizePlanChecklist(plan, 'done');
assert.deepEqual(terminal.map(item => item.status), ['done', 'failed', 'done'], 'terminal success never erases a known failed step');

const frame = stripAnsi(await renderInkFrame(
    <NexusWorkspacePanel
        timeline={[]}
        usage={{contextTokens: 0, contextLimit: 0, inputTokens: 0, outputTokens: 0, source: 'unavailable'}}
        mode="workspace"
        agents={[]}
        tasks={[]}
        touchedFiles={[]}
        activityItems={[]}
        pendingQuestion={null}
        selectedQuestionIndex={0}
        planItems={plan}
        planStatus={planChecklistStatus(plan)}
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
        width={72}
        height={30}
        currentTask=""
        isWorking={true}
        workingPhase="tool"
        elapsedMs={2000}
    />,
    72,
    30
));
assert.match(frame, /WORKSPACE/);
assert.match(frame, /PLAN\s+running/);
assert.match(frame, /Inspect current rendering/);
assert.match(frame, /Implement progress rows/);
assert.match(frame, /Run TUI tests/);
assert.doesNotMatch(frame, /PRIVATE_REASONING|chain.of.thought/i);

console.log('Persistent live plan checklist state and render tests passed');
