import assert from 'node:assert/strict';
import {activityFromWorkEvent, fileStatusFromWorkEvent, mergeActivityTargetFields, type ActivityItem} from './helpers.js';
import {activityKindLabel, activityStatusWord} from './inline-activity.js';
import {phaseDisplayLabel} from './banner.js';

const cases = [
    [{event_type: 'plan.started', status: 'running', steps: [{description: 'Inspect code'}, {description: 'Run tests'}]}, 'plan', 'PLAN'],
    [{event_type: 'command.started', status: 'running', command: 'npm test', tool: 'terminal'}, 'terminal', 'TERMINAL'],
    [{event_type: 'web.search', status: 'running', query: 'Ink terminal UI', tool: 'web_search'}, 'search', 'SEARCH'],
    [{event_type: 'test.started', status: 'running', target: 'tui', tool: 'test_runner'}, 'test', 'TEST'],
    [{event_type: 'subagent.started', status: 'running', related_subagent: 'reviewer', target: 'Review layout'}, 'hive', 'HIVE'],
    [{event_type: 'approval.requested', status: 'pending', target: 'Run command'}, 'approval', 'APPROVAL'],
    [{event_type: 'skill.started', kind: 'skill', status: 'running', tool: 'skill__code_review', target: 'Review changes'}, 'skill', 'SKILL'],
    [{event_type: 'tool.started', kind: 'mcp', status: 'running', tool: 'mcp__github__search_code', target: 'fallback'}, 'mcp', 'MCP'],
    [{event_type: 'error.raised', status: 'failed', error: 'boom'}, 'error', 'ERROR']
] as const;

for (const [event, expectedKind, expectedLabel] of cases) {
    const activity = activityFromWorkEvent({...event});
    assert.equal(activity.kind, expectedKind);
    assert.equal(activityKindLabel(activity.kind), expectedLabel);
}

const plan = activityFromWorkEvent({
    event_type: 'plan.started',
    status: 'running',
    steps: [{description: 'Inspect code'}, {description: 'Run tests'}]
});
assert.equal(plan.summary, '2 steps');
assert.match(plan.detail || '', /1\. Inspect code/);
assert.match(plan.detail || '', /2\. Run tests/);

const searchStart = activityFromWorkEvent({
    event_type: 'web.started', kind: 'search', status: 'running',
    tool: 'web_search', query: 'today news headlines'
});
const searchFinishedWithoutTarget = activityFromWorkEvent({
    event_type: 'web.result', kind: 'search', status: 'failed',
    tool: 'web_search', duration_ms: 14000, error: 'provider unavailable'
});
const mergedSearch = mergeActivityTargetFields(
    {...searchStart, id: 'search', number: 1} as ActivityItem,
    searchFinishedWithoutTarget
);
assert.equal(mergedSearch.summary, 'today news headlines');
assert.equal(mergedSearch.command, 'today news headlines');

const fileStart = activityFromWorkEvent({
    event_type: 'file.read', kind: 'file', status: 'running',
    tool: 'reading', path: 'src/providers/fallback.ts'
});
const fileFinishedWithoutTarget = activityFromWorkEvent({
    event_type: 'file.read', kind: 'file', status: 'done',
    tool: 'reading', duration_ms: 8000
});
const mergedFile = mergeActivityTargetFields(
    {...fileStart, id: 'file', number: 2} as ActivityItem,
    fileFinishedWithoutTarget
);
assert.equal(mergedFile.summary, 'src/providers/fallback.ts');
assert.deepEqual(mergedFile.files, ['src/providers/fallback.ts']);

assert.equal(fileStatusFromWorkEvent({
    event_type: 'file.read', kind: 'file', action: 'Read file', path: 'src/readme.md', status: 'done'
}), null, 'reads do not appear as changes');
assert.deepEqual(fileStatusFromWorkEvent({
    event_type: 'file.edited', kind: 'file', action: 'Edit file', path: 'src/app.ts', status: 'done',
    changed_lines: {added: 4, removed: 2}
}), {
    name: 'src/app.ts', status: 'EDIT FILE', additions: 4, deletions: 2
});
assert.deepEqual(fileStatusFromWorkEvent({
    event_type: 'file.created', kind: 'file', action: 'Create file', path: 'src/new.ts', status: 'done'
}), {
    name: 'src/new.ts', status: 'CREATE FILE'
}, 'unknown counts stay unknown instead of becoming +0/-0');

assert.equal(activityStatusWord('running'), 'LIVE');
assert.equal(activityStatusWord('done'), 'DONE');
assert.equal(activityStatusWord('failed'), 'FAIL');
assert.equal(activityStatusWord('blocked'), 'WAIT');
assert.equal(phaseDisplayLabel('hive'), 'Coordinating Hive agents');
assert.equal(phaseDisplayLabel('verifying'), 'Running verification');

console.log('Live trace taxonomy tests passed');
