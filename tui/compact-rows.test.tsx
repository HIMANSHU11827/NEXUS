/**
 * Nexus TUI v3.0 — Compact row & boxed-surface render tests.
 * Deterministic, offline: pure helpers plus Ink frames over a fake stream.
 */
import assert from 'node:assert/strict';
import {activityFromWorkEvent, getFileName, type ActivityItem, type Message} from './helpers.js';
import {resolveTuiLayout} from './layout.js';
import {isExplicitInspectorShortcut, resolveTabIntent} from './interaction-state.js';

// Ink colorizes via chalk, which keys off the real process stdout; tests run
// with piped output, so force color output before any chalk-importing module
// is evaluated. Static imports would load chalk too early, hence the dynamic
// imports below.
process.env.FORCE_COLOR = '3';
const React = (await import('react')).default;
const {Box} = await import('ink');
const {ChatLineView, MESSAGE_BORDER_COLUMNS, buildChatLines, messageBorderColor} = await import('./chat-view.js');
const {InlineActivity} = await import('./inline-activity.js');
const {renderInkFrame, stripAnsi} = await import('./render-test-utils.js');
const {getTheme, TRANSCRIPT_SURFACE_BG} = await import('./theme.js');

// ── helpers smoke ────────────────────────────────────────────────────────
assert.equal(getFileName('C:\\workspace\\src\\providers\\fallback.ts'), 'fallback.ts');
assert.equal(MESSAGE_BORDER_COLUMNS, 2);
const theme = getTheme();
assert.equal(messageBorderColor('user'), theme.userColor);
assert.equal(messageBorderColor('assistant'), theme.warning);
assert.equal(messageBorderColor('system'), null);
assert.equal(messageBorderColor(undefined), null);

// ── compact row content: basename not full path, elapsed time, no noise ──
const fileActivity: ActivityItem = {
    id: 'f1', number: 1, kind: 'file', title: 'Edited file', status: 'done',
    toolName: 'apply_patch', summary: 'C:\\workspace\\src\\providers\\fallback.ts',
    files: ['C:\\workspace\\src\\providers\\fallback.ts'], durationMs: 8000
};
const fileFrame = stripAnsi(await renderInkFrame(
    <Box width={60} flexDirection="column">
        <ChatLineView line={{key: 'f1', text: '', color: 'grey', activityId: 'f1', activity: fileActivity}} width={60} frame={1} />
    </Box>,
    60,
    5
));
assert.match(fileFrame, /FILE · apply patch · fallback\.ts · 8s/);
assert.doesNotMatch(fileFrame, /workspace\\src\\providers|C:\\workspace/);
assert.doesNotMatch(fileFrame, /\[(?:DONE|FAIL|LIVE)\]/);

const millisActivity: ActivityItem = {
    id: 'f2', number: 2, kind: 'file', title: 'Read file', status: 'done',
    toolName: 'reading', summary: 'src/main.py', files: ['src/main.py'], durationMs: 412
};
const millisFrame = stripAnsi(await renderInkFrame(
    <Box width={60} flexDirection="column">
        <ChatLineView line={{key: 'f2', text: '', color: 'grey', activityId: 'f2', activity: millisActivity}} width={60} frame={1} />
    </Box>,
    60,
    5
));
assert.match(millisFrame, /FILE · reading · main\.py · 412ms/);

// ── failed rows: fully red, no verbose failure text, no status brackets ──
const failedActivity: ActivityItem = {
    id: 'bad', number: 3, kind: 'search', title: 'Searching', status: 'failed',
    toolName: 'web_search', summary: 'latest release notes',
    error: 'provider unavailable: gateway refused the request', durationMs: 1500
};
const failedRaw = await renderInkFrame(
    <Box width={60} flexDirection="column">
        <InlineActivity activity={failedActivity} width={60} frame={1} />
    </Box>,
    60,
    5
);
const errorColor = `38;2;${theme.statusError.slice(1).match(/../g)?.map(part => parseInt(part, 16)).join(';')}`;
// The whole row (chevron + label + duration) is one red span; chalk merges
// the two Text nodes into a single colorized run.
const redRowSpan = `\u001b[${errorColor}m› SEARCH · web search · latest release notes · 2s\u001b[39m`;
assert.ok(failedRaw.includes(redRowSpan), `failed row should be fully red (saw ${JSON.stringify(failedRaw)})`);
const failedPlain = stripAnsi(failedRaw);
assert.match(failedPlain, /SEARCH · web search · latest release notes · 2s/);
assert.doesNotMatch(failedPlain, /provider unavailable|\[(?:DONE|FAIL|LIVE)\]/);
assert.doesNotMatch(failedRaw, /\[(?:DONE|FAIL|LIVE)\]/);

const doneRaw = await renderInkFrame(
    <Box width={60} flexDirection="column">
        <InlineActivity activity={{...failedActivity, status: 'done', error: undefined}} width={60} frame={1} />
    </Box>,
    60,
    5
);
assert.equal((doneRaw.match(new RegExp(errorColor, 'g')) || []).length, 0, 'completed rows must not be red');

// ── boxed message surfaces: role borders, shared surface background ──────
const boxedLines = buildChatLines([
    {role: 'user', content: 'Explain this'},
    {role: 'assistant', content: 'Here is the explanation.'}
], [], 40, null, null, false);
assert.equal(boxedLines.find(line => line.key.startsWith('user-'))?.backgroundColor, TRANSCRIPT_SURFACE_BG);
assert.equal(boxedLines.find(line => line.key.startsWith('user-'))?.surface, 'user');
assert.ok(boxedLines.filter(line => line.surface === 'user').length >= 2, 'short user boxes should be at least two rows high');
assert.equal(boxedLines.find(line => line.key.startsWith('assistant-'))?.backgroundColor, TRANSCRIPT_SURFACE_BG);
assert.equal(boxedLines.find(line => line.key.startsWith('assistant-'))?.surface, 'assistant');
const boxedRaw = await renderInkFrame(
    <Box width={40} flexDirection="column">
        {boxedLines.map(line => <ChatLineView key={line.key} line={line} width={40} frame={1} />)}
    </Box>,
    40,
    10
);
const rgb = (hex: string) => `38;2;${(hex.slice(1).match(/../g) || []).map(part => parseInt(part, 16)).join(';')}`;
assert.ok(boxedRaw.includes(rgb(theme.userColor)), 'user border should use blue');
assert.ok(boxedRaw.includes(rgb(theme.warning)), 'assistant border should use orange');
const boxedPlain = stripAnsi(boxedRaw);
const boxedRows = boxedPlain.replace(/\r/g, '').split('\n').filter(line => line.trim().length > 0);
assert.ok(boxedRows.length >= 2, 'both message surfaces should render');
for (const line of boxedRows) {
    assert.ok(line.startsWith('│') && line.endsWith('│'), `boxed line should carry both border rails: ${JSON.stringify(line)}`);
}
assert.ok(boxedRows.some(line => line.includes('Explain this')), 'user content should sit inside the boxed surface');
assert.ok(boxedRows.some(line => line.includes('you >')), 'user box should use the user prompt label');
assert.ok(boxedRows.some(line => line.includes('Here is the explanation.')), 'assistant content should sit inside the boxed surface');
assert.ok((boxedPlain.match(/│/g) || []).length >= 4, 'both surfaces should draw left+right border rails');

const lastUserSurface = Math.max(...boxedLines.map((line, index) => line.surface === 'user' ? index : -1));
const firstAssistantSurface = boxedLines.findIndex(line => line.surface === 'assistant');
const betweenSurfaces = boxedLines.slice(lastUserSurface + 1, firstAssistantSurface);
assert.equal(betweenSurfaces.length, 1, 'user and NEXUS boxes should have exactly one blank row between them');
assert.equal(betweenSurfaces[0]?.text, '');
assert.equal(betweenSurfaces[0]?.surface, undefined);

const shortUserLines = buildChatLines([{role: 'user', content: 'hello'}], [], 40, null, null, false);
const shortUserRaw = stripAnsi(await renderInkFrame(
    <Box width={40} flexDirection="column">
        {shortUserLines.map(line => <ChatLineView key={line.key} line={line} width={40} frame={1} />)}
    </Box>,
    40,
    5
));
const shortUserRows = shortUserLines.filter(line => line.surface === 'user');
assert.equal(shortUserRows.length, 2, 'a short user message should render in a two-row box');
assert.equal(shortUserRows[0]?.prefix, 'you > ');
assert.equal(shortUserRows[0]?.text, 'hello');
assert.equal(shortUserRows[0]?.bold, true, 'user text should be visually emphasized');
assert.ok(!shortUserRows[1]?.prefix);
assert.equal(shortUserRows[1]?.text, '');
assert.notEqual(shortUserRows[1]?.bold, true, 'blank padding should not be bold');

const wrappedUserRows = buildChatLines([{role: 'user', content: 'This is a deliberately long user message that wraps across multiple rows.'}], [], 40, null, null, false)
    .filter(line => line.surface === 'user' && line.text.trim().length > 0);
assert.ok(wrappedUserRows.length > 1, 'long user messages should wrap');
assert.ok(wrappedUserRows.every(line => line.bold === true), 'wrapped user text rows should remain bold');

const assistantLine = buildChatLines([{role: 'assistant', content: 'NEXUS reply'}], [], 40, null, null, false)
    .find(line => line.surface === 'assistant');
assert.notEqual(assistantLine?.bold, true, 'assistant styling should remain independent');
assert.match(shortUserRaw, /you >/);
assert.match(shortUserRaw, /hello/);

// activity rows must NOT draw message borders
const activityOnly = stripAnsi(await renderInkFrame(
    <Box width={60} flexDirection="column">
        <ChatLineView line={{key: 'a', text: '', color: 'grey', activityId: 'f1', activity: fileActivity}} width={60} frame={1} />
    </Box>,
    60,
    5
));
assert.doesNotMatch(activityOnly, /│/);

// expanded activity details surface the full error text; the compact row does not
const expandedLines = buildChatLines([
    {role: 'activity', content: 'Searching', activityId: 'bad'}
], [failedActivity], 60, 'bad', 'bad', false);
const expandedPlain = stripAnsi(await renderInkFrame(
    <Box width={60} flexDirection="column">
        {expandedLines.map(line => <ChatLineView key={line.key} line={line} width={60} frame={1} />)}
    </Box>,
    60,
    30
));
assert.match(expandedPlain, /provider unavailable/, 'expanded details must show the full error text');

// Activity rows need a breathing row before the assistant surface.
const activityToAssistantLines = buildChatLines([
    {role: 'activity', content: 'Reading', activityId: 'f1'},
    {role: 'assistant', content: 'The file is ready.'}
], [fileActivity], 60, null, null, false);
const activityRowIndex = activityToAssistantLines.findIndex(line => line.activity?.id === 'f1');
const assistantSurfaceIndex = activityToAssistantLines.findIndex(line => line.surface === 'assistant');
assert.ok(activityRowIndex >= 0, 'activity row should be present before the assistant');
assert.ok(assistantSurfaceIndex > activityRowIndex, 'assistant surface should follow the activity row');
const activityAssistantGap = activityToAssistantLines.slice(activityRowIndex + 1, assistantSurfaceIndex);
assert.equal(activityAssistantGap.length, 1, 'activity and assistant should have exactly one blank row between them');
assert.equal(activityAssistantGap[0]?.text, '');
assert.equal(activityAssistantGap[0]?.activity, undefined);
assert.equal(activityAssistantGap[0]?.surface, undefined);

// ── narrow width: boxed surfaces and compact rows never overflow ─────────
const longUser = 'word '.repeat(60).trim();
const narrowLines = buildChatLines([
    {role: 'user', content: longUser},
    {role: 'assistant', content: `The ${longUser} response`},
    {role: 'activity', content: 'Searching', activityId: 'f1'}
], [fileActivity], 20, null, null, false);
const narrowPlain = stripAnsi(await renderInkFrame(
    <Box width={20} flexDirection="column">
        {narrowLines.map(line => <ChatLineView key={line.key} line={line} width={20} frame={1} />)}
    </Box>,
    20,
    40
));
for (const line of narrowPlain.replace(/\r/g, '').split('\n')) {
    assert.ok([...line].length <= 20, `narrow render overflow: ${JSON.stringify(line)}`);
}
const longPathActivity: ActivityItem = {
    id: 'lp', number: 4, kind: 'file', title: 'Edited file', status: 'done',
    toolName: 'apply_patch', summary: 'C:\\very\\long\\nested\\directory\\structure\\that\\keeps\\going\\deep\\fallback.ts',
    files: ['C:\\very\\long\\nested\\directory\\structure\\that\\keeps\\going\\deep\\fallback.ts'], durationMs: 900
};
const narrowRowPlain = stripAnsi(await renderInkFrame(
    <Box width={20} flexDirection="column">
        <ChatLineView line={{key: 'lp', text: '', color: 'grey', activityId: 'lp', activity: longPathActivity}} width={20} frame={1} />
    </Box>,
    20,
    5
));
assert.ok(narrowRowPlain.includes('…'), 'compact rows should ellipsis-truncate on narrow terminals');
assert.ok([...narrowRowPlain.trim().split('\n')[0]].length <= 20, 'compact row should fit narrow width');

// resolveTuiLayout must never produce negative or zero-sized columns
for (let w = 1; w <= 160; w += 7) {
    for (let h = 5; h <= 40; h += 5) {
        const l = resolveTuiLayout(w, h);
        assert.ok(l.sidebarWidth >= 0, `negative sidebarWidth at ${w}x${h}`);
        assert.ok(l.mainWidth >= 1, `zero mainWidth at ${w}x${h}`);
        assert.ok(l.chatContentWidth >= 1, `zero chatContentWidth at ${w}x${h}`);
        assert.ok(l.chatViewportHeight >= 1, `zero chatViewportHeight at ${w}x${h}`);
        assert.equal(l.mainWidth + l.sidebarWidth, l.width);
    }
}

// ── every activity kind flows through the same compact row renderer ──────
const kinds: ActivityItem[] = [
    {id: 'k-plan', number: 1, kind: 'plan', title: 'Planning', status: 'done', toolName: 'plan', summary: '3 steps', durationMs: 120},
    {id: 'k-tool', number: 2, kind: 'tool', title: 'Reading', status: 'done', toolName: 'read_file', summary: 'src/app.ts', durationMs: 300},
    {id: 'k-search', number: 3, kind: 'search', title: 'Searching', status: 'done', toolName: 'web_search', summary: 'Ink layouts', durationMs: 1500},
    {id: 'k-file', number: 4, kind: 'file', title: 'Edited', status: 'done', toolName: 'edit', summary: 'tui/chat-view.tsx', files: ['tui/chat-view.tsx'], durationMs: 200},
    {id: 'k-terminal', number: 5, kind: 'terminal', title: 'Running', status: 'done', toolName: 'terminal', command: 'npm test', summary: 'npm test', durationMs: 4200},
    {id: 'k-hive', number: 6, kind: 'hive', title: 'Subagent', status: 'running', toolName: 'hive', summary: 'Review the diff', relatedSubagent: 'reviewer-7'},
    {id: 'k-mcp', number: 7, kind: 'mcp', title: 'MCP call', status: 'done', toolName: 'mcp__filesystem__list', summary: '/tmp', durationMs: 40},
    {id: 'k-skill', number: 8, kind: 'skill', title: 'Skill', status: 'done', toolName: 'skill__code_review', summary: 'Review changes', durationMs: 500},
    {id: 'k-approval', number: 9, kind: 'approval', title: 'Approval', status: 'pending', toolName: 'approval', summary: 'Run risky command', durationMs: 100},
    {id: 'k-retry', number: 10, kind: 'retry', title: 'Retry', status: 'running', toolName: 'retry', summary: 'web_search', durationMs: 700},
    {id: 'k-test', number: 11, kind: 'test', title: 'Testing', status: 'done', toolName: 'pytest', summary: 'tests/test_events.py', durationMs: 6000},
    {id: 'k-error', number: 12, kind: 'error', title: 'Failed', status: 'failed', toolName: 'error', summary: '', error: 'boom'}
];
const kindPlain = stripAnsi(await renderInkFrame(
    <Box width={90} flexDirection="column">
        {kinds.map(activity => (
            <ChatLineView key={activity.id} line={{key: `k-${activity.id}`, text: '', color: 'grey', activityId: activity.id, activity}} width={90} frame={1} />
        ))}
    </Box>,
    90,
    30
));
for (const label of ['PLAN', 'TOOL', 'SEARCH', 'FILE', 'TERMINAL', 'HIVE', 'MCP', 'SKILL', 'APPROVAL', 'RETRY', 'TEST', 'ERROR']) {
    assert.ok(kindPlain.includes(label), `missing kind label ${label}`);
}
assert.match(kindPlain, /reviewer-7/, 'hive rows should surface the subagent id');
assert.match(kindPlain, /npm test · 4s/);
assert.match(kindPlain, /chat-view\.tsx/); // file rows use basenames

// ── activityFromWorkEvent carries the hive subagent id ───────────────────
const subagentEvent = activityFromWorkEvent({
    event_type: 'subagent.started', kind: 'subagent', status: 'running',
    related_subagent: 'writer', target: 'Draft the report'
});
assert.equal(subagentEvent.kind, 'hive');
assert.equal(subagentEvent.relatedSubagent, 'writer');
assert.equal(subagentEvent.summary, 'Draft the report');

// ── Ctrl+I / Tab inspector determinism contract ──────────────────────────
// Windows Terminal reports Ctrl+I as Tab (same ASCII byte): no ctrl flag.
assert.equal(isExplicitInspectorShortcut('', false), false);
assert.equal(isExplicitInspectorShortcut('i', true), true);
assert.equal(isExplicitInspectorShortcut('o', true), true);
assert.equal(resolveTabIntent({paletteOpen: true, hasActivityRows: true}), 'complete-palette');
assert.equal(resolveTabIntent({paletteOpen: true, hasActivityRows: false}), 'complete-palette');
assert.equal(resolveTabIntent({paletteOpen: false, hasActivityRows: true}), 'cycle-activity');
assert.equal(resolveTabIntent({paletteOpen: false, hasActivityRows: true, shift: true}), 'cycle-activity');
assert.equal(resolveTabIntent({paletteOpen: false, hasActivityRows: false}), 'cycle-inspector');
assert.equal(resolveTabIntent({paletteOpen: false, hasActivityRows: true, ctrl: true}), 'cycle-inspector');

console.log('Compact row & boxed-surface render tests passed');
