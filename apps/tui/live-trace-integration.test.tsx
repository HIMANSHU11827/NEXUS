import React from 'react';
import assert from 'node:assert/strict';
import {Box} from 'ink';
import {ChatLineView, activityIdsFromChatLines, buildChatLines, nextActivityFocus, toggleActivityExpansion} from './chat-view.js';
import {InlineActivity} from './inline-activity.js';
import {activityFromWorkEvent, canonicalActivityFromSseFrame, type ActivityItem, type Message} from './helpers.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';
import {TRANSCRIPT_SURFACE_BG} from './theme.js';

const events = [
    {event_type: 'plan.started', kind: 'plan', status: 'running', steps: [{description: 'Inspect code'}]},
    {event_type: 'tool.started', kind: 'tool', status: 'running', tool: 'read_file', target: 'src/app.ts'},
    {event_type: 'command.started', kind: 'command', status: 'running', tool: 'terminal', command: 'npm test'},
    {event_type: 'web.navigate', kind: 'browser', status: 'running', tool: 'browser', target: 'docs.example.com'},
    {event_type: 'search.started', kind: 'search', status: 'running', tool: 'web_search', query: 'Ink layouts'},
    {event_type: 'file.edited', kind: 'file', status: 'done', tool: 'apply_patch', path: 'src/app.ts'},
    {event_type: 'test.started', kind: 'test', status: 'running', tool: 'test_runner', target: 'tui'},
    {event_type: 'subagent.started', kind: 'subagent', status: 'running', related_subagent: 'reviewer', target: 'Review UI'},
    {event_type: 'skill.completed', kind: 'skill', status: 'done', tool: 'skill__code_review', target: 'Review changes'},
    {event_type: 'tool.completed', kind: 'mcp', status: 'done', tool: 'mcp__github__search_code', target: 'fallback'},
    {event_type: 'approval.requested', kind: 'approval', status: 'pending', target: 'Run command'},
    {event_type: 'error.raised', kind: 'error', status: 'failed', error: 'Command failed'}
];

const activities: ActivityItem[] = events.map((event, index) => {
    const frame = `event: nexus.event\ndata: ${JSON.stringify({event})}\n\n`;
    const parsed = canonicalActivityFromSseFrame(frame);
    assert.ok(parsed, `SSE event ${index + 1} should parse`);
    return {...activityFromWorkEvent(parsed), id: `trace-${index + 1}`, number: index + 1};
});

assert.deepEqual(
    activities.map(activity => activity.kind),
    ['plan', 'tool', 'terminal', 'browser', 'search', 'file', 'test', 'hive', 'skill', 'mcp', 'approval', 'error']
);

const history: Message[] = [
    {role: 'user', content: 'Trace this work'},
    {role: 'assistant', content: 'I am tracing the confirmed work.'},
    ...activities.map(activity => ({role: 'activity' as const, content: activity.title, activityId: activity.id}))
];
const lines = buildChatLines(history, activities, 110, null, null, false);
const activityIds = activityIdsFromChatLines(lines);
assert.equal(activityIds.length, activities.length);
assert.equal(nextActivityFocus(activityIds, null), 'trace-1');
assert.equal(nextActivityFocus(activityIds, 'trace-1'), 'trace-2');
assert.equal(nextActivityFocus(activityIds, 'trace-1', true), 'trace-12');
assert.equal(toggleActivityExpansion(null, 'trace-1'), 'trace-1');
assert.equal(toggleActivityExpansion('trace-1', 'trace-1'), null);
assert.equal(lines.find(line => line.key.startsWith('user-'))?.backgroundColor, '#292929');
assert.equal(lines.find(line => line.key.startsWith('assistant-'))?.backgroundColor, '#292929');
assert.equal(lines.some(line => line.key.startsWith('activity-plan-')), false, 'plan details should be collapsed by default');
const expandedPlanLines = buildChatLines(history, activities, 110, 'trace-1', 'trace-1', false);
const planDetailLines = expandedPlanLines.filter(line => line.key.startsWith('activity-plan-'));
assert.ok(planDetailLines.length > 0, 'plan details should expand like every other activity');
assert.ok(planDetailLines.every(line => line.backgroundColor === '#292929'), 'expanded plan details should use the transcript surface');
assert.equal(planDetailLines.some(line => /[┌┐└┘│]/.test(`${line.prefix || ''}${line.text}`)), false, 'expanded plan details should not draw a border');
const expandedFileLines = buildChatLines(history, activities, 110, 'trace-6', 'trace-6', false);
const fileDetailLines = expandedFileLines.filter(line => line.key.startsWith('activity-detail-'));
assert.ok(fileDetailLines.length > 0);
assert.ok(fileDetailLines.every(line => line.backgroundColor === '#292929'), 'expanded details should use the transcript surface');
assert.equal(fileDetailLines.some(line => /[┌┐└┘│]/.test(line.text)), false, 'expanded details should not draw a border');

const frame = await renderInkFrame(
    <Box width={110} flexDirection="column">
        {lines.map(line => <ChatLineView key={line.key} line={line} width={110} frame={1} />)}
    </Box>,
    110,
    40
);
assert.equal(TRANSCRIPT_SURFACE_BG, '#292929');
type ActivitySurfaceElement = React.ReactElement<{backgroundColor?: string}>;
const activityRenderer = InlineActivity as unknown as {type: (props: Record<string, unknown>) => ActivitySurfaceElement};
const collapsedActivitySurface = activityRenderer.type({
    activity: activities[1], width: 110, frame: 1, focused: false, expanded: false
});
const expandedActivitySurface = activityRenderer.type({
    activity: activities[1], width: 110, frame: 1, focused: true, expanded: true
});
assert.equal(collapsedActivitySurface.props.backgroundColor, TRANSCRIPT_SURFACE_BG, 'collapsed activities should use the transcript surface');
assert.equal(expandedActivitySurface.props.backgroundColor, TRANSCRIPT_SURFACE_BG, 'expanded activities should retain the transcript surface');
const plain = stripAnsi(frame);
for (const label of ['plan', 'read file', 'terminal · npm test', 'browser · docs.example.com', 'web search · Ink layouts', 'apply patch · app.ts', 'test runner · tui', 'hive · Review UI', 'code review · Review changes', 'github/search code · fallback', 'approval · Run command', 'error']) {
    assert.match(plain, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'));
}
assert.doesNotMatch(plain, /\[(?:DONE|FAIL|LIVE)\]|Failed ·/);
assert.match(plain, /you >/);
assert.match(plain, /Trace this work/);
assert.match(plain, /Nexus > I am tracing the confirmed work\./);
assert.equal((plain.match(/›/g) || []).length, activities.length, 'every activity should expose a disclosure chevron');

const consecutiveToolActivities: ActivityItem[] = [
    {id: 'tool-gap-1', number: 1, kind: 'tool', title: 'Reading', status: 'done', toolName: 'read_file', summary: 'src/app.ts'},
    {id: 'tool-gap-2', number: 2, kind: 'tool', title: 'Reading', status: 'done', toolName: 'read_file', summary: 'src/helpers.ts'},
    {id: 'tool-gap-3', number: 3, kind: 'tool', title: 'Reading', status: 'done', toolName: 'read_file', summary: 'src/types.ts'}
];
const consecutiveToolHistory: Message[] = consecutiveToolActivities.map(activity => ({
    role: 'activity', content: activity.title, activityId: activity.id
}));
const consecutiveToolLines = buildChatLines(consecutiveToolHistory, consecutiveToolActivities, 90, null, null, false);
const consecutiveToolFrame = stripAnsi(await renderInkFrame(
    <Box width={90} flexDirection="column">
        {consecutiveToolLines.map(line => <ChatLineView key={line.key} line={line} width={90} frame={1} />)}
    </Box>,
    90,
    10
));
const consecutiveToolRows = consecutiveToolFrame.replace(/\r/g, '').split('\n');
const firstToolRow = consecutiveToolRows.findIndex(row => row.includes('app.ts'));
const secondToolRow = consecutiveToolRows.findIndex(row => row.includes('helpers.ts'));
const thirdToolRow = consecutiveToolRows.findIndex(row => row.includes('types.ts'));
assert.equal(secondToolRow - firstToolRow, 2, 'two consecutive tools should have one blank row between them');
assert.equal(thirdToolRow - secondToolRow, 2, 'three consecutive tools should keep one blank row between each');

const retryActivities: ActivityItem[] = [
    {id: 'search-fail-1', number: 1, kind: 'search', title: 'Searching', summary: 'web_search', status: 'failed', toolName: 'web_search', error: 'provider unavailable'},
    {id: 'search-ok', number: 2, kind: 'search', title: 'Searching', summary: 'https://www.example.com/news/today', status: 'done', toolName: 'web_search'},
    {id: 'search-fail-2', number: 3, kind: 'search', title: 'Searching', summary: 'search', status: 'failed', toolName: 'search', error: 'provider unavailable'},
    {id: 'search-fail-3', number: 4, kind: 'search', title: 'Searching', summary: 'web-search', status: 'failed', toolName: 'web_search', error: 'provider unavailable'}
];
const retryHistory: Message[] = [
    {role: 'user', content: 'Find the latest news'},
    ...retryActivities.map(activity => ({role: 'activity' as const, content: activity.title, activityId: activity.id}))
];
const retryLines = buildChatLines(retryHistory, retryActivities, 100, null, null, false);
assert.equal(activityIdsFromChatLines(retryLines).length, 4, 'every search attempt must remain visible');
const retryFrame = stripAnsi(await renderInkFrame(
    <Box width={100} flexDirection="column">
        {retryLines.map(line => <ChatLineView key={line.key} line={line} width={100} frame={1} />)}
    </Box>,
    100,
    20
));
assert.match(retryFrame, /web search · example\.com/);
assert.doesNotMatch(retryFrame, /\[(?:DONE|FAIL|LIVE)\]|Failed ·/);
const canonicalUrlSearch = activityFromWorkEvent({
    event_type: 'web.navigate', kind: 'search', status: 'done', tool: 'web_search',
    url: 'https://www.example.org/articles/latest'
});
assert.equal(canonicalUrlSearch.summary, 'https://www.example.org/articles/latest');

const fileNameActivity: ActivityItem = {
    id: 'file-name', number: 20, kind: 'file', title: 'Read file', status: 'done',
    toolName: 'reading', summary: 'C:\\workspace\\src\\providers\\fallback.ts',
    files: ['C:\\workspace\\src\\providers\\fallback.ts'], durationMs: 8000
};
const fileNameFrame = stripAnsi(await renderInkFrame(
    <Box width={100} flexDirection="column">
        <ChatLineView
            line={{key: 'file-name', text: '', color: 'grey', activityId: fileNameActivity.id, activity: fileNameActivity}}
            width={100}
            frame={1}
        />
    </Box>,
    100,
    5
));
assert.match(fileNameFrame, /reading · fallback\.ts · 8s/);

const runningHive: ActivityItem = {
    id: 'running-hive', number: 21, kind: 'hive', title: 'Testing agent', status: 'running',
    toolName: 'testing-agent', summary: 'Testing agent · checking edge cases',
    startedAt: Date.now() - 8000
};
const runningHiveFrame = stripAnsi(await renderInkFrame(
    <Box width={100} flexDirection="column">
        <ChatLineView
            line={{key: 'running-hive', text: '', color: 'grey', activityId: runningHive.id, activity: runningHive}}
            width={100}
            frame={1}
        />
    </Box>,
    100,
    5
));
assert.match(runningHiveFrame, /testing agent · checking edge cases · (?:8|9)s/);
assert.doesNotMatch(runningHiveFrame, /testing agent · Testing agent/i);

const boundaryActivities: ActivityItem[] = [
    {id: 'turn-1a', number: 1, kind: 'search', title: 'Searching', summary: 'search', status: 'failed', toolName: 'search', error: 'provider unavailable'},
    {id: 'turn-1b', number: 2, kind: 'search', title: 'Searching', summary: 'web_search', status: 'failed', toolName: 'web_search', error: 'rate limit'},
    {id: 'turn-2', number: 3, kind: 'search', title: 'Searching', summary: 'search', status: 'failed', toolName: 'search', error: 'provider unavailable'}
];
const boundaryLines = buildChatLines([
    {role: 'user', content: 'First search'},
    {role: 'activity', content: 'Provider failed', activityId: 'turn-1a'},
    {role: 'activity', content: 'Rate limited', activityId: 'turn-1b'},
    {role: 'user', content: 'Second search'},
    {role: 'activity', content: 'Provider failed again', activityId: 'turn-2'}
], boundaryActivities, 100, null, null, false);
assert.equal(activityIdsFromChatLines(boundaryLines).length, 3, 'distinct errors and later user turns must remain visible');

const searchThenAssistant: ActivityItem = {
    id: 'search-before-answer', number: 4, kind: 'search', title: 'Searching',
    summary: "today's top news", status: 'done', toolName: 'web_search'
};
const searchAnswerLines = buildChatLines([
    {role: 'activity', content: searchThenAssistant.title, activityId: searchThenAssistant.id},
    {role: 'assistant', content: 'Here is the news roundup.'}
], [searchThenAssistant], 100, null, null, false);
const searchRow = searchAnswerLines.findIndex(line => line.activity?.id === searchThenAssistant.id);
const answerRow = searchAnswerLines.findIndex(line => line.surface === 'assistant');
const rowsBetweenSearchAndAnswer = searchAnswerLines.slice(searchRow + 1, answerRow);
assert.equal(rowsBetweenSearchAndAnswer.length, 1, 'search activity and NEXUS output need one blank row between them');
assert.equal(rowsBetweenSearchAndAnswer[0]?.text, '');
assert.equal(rowsBetweenSearchAndAnswer[0]?.activity, undefined);

const expandedSearchLines = buildChatLines([
    {role: 'activity', content: searchThenAssistant.title, activityId: searchThenAssistant.id},
    {role: 'assistant', content: 'Here is the expanded news roundup.'}
], [{...searchThenAssistant, detail: 'query: today\'s top news'}], 100, searchThenAssistant.id, searchThenAssistant.id, false);
const expandedSearchRow = expandedSearchLines.findIndex(line => line.activity?.id === searchThenAssistant.id);
const expandedAnswerRow = expandedSearchLines.findIndex(line => line.surface === 'assistant');
const rowsBetweenExpandedSearchAndAnswer = expandedSearchLines.slice(expandedSearchRow + 1, expandedAnswerRow);
assert.ok(rowsBetweenExpandedSearchAndAnswer.length >= 2, 'expanded search details should retain a final separator before NEXUS output');
assert.equal(rowsBetweenExpandedSearchAndAnswer.at(-1)?.text, '');
assert.equal(rowsBetweenExpandedSearchAndAnswer.at(-1)?.activityId, searchThenAssistant.id);

console.log('Live trace SSE-to-render integration tests passed');
