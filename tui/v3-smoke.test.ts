/**
 * Nexus TUI v3.0 — Component Smoke Test
 */
import {getTheme, activityColor, activityGlyph, statusColor, statusGlyph} from './theme.js';
import type {ActivityItem, AgentInfo, TaskItem} from './types.js';

let pass = 0, fail = 0;
function t(label: string, ok: boolean) {
    if (ok) { pass++; console.log(`  ✅ ${label}`); }
    else { fail++; console.log(`  ❌ ${label}`); }
}

console.log('═══ Nexus TUI v3.0 — Component Smoke ═══\n');

// Theme
const theme = getTheme();
t('getTheme() returns object', typeof theme === 'object' && theme !== null);
t('theme has primary color', typeof theme.primary === 'string');
t('theme has status colors', !!theme.statusRunning && !!theme.statusDone && !!theme.statusError);

// Activity colors
t('activityColor("tool") returns string', typeof activityColor('tool') === 'string');
t('activityColor("hive") returns string', typeof activityColor('hive') === 'string');
t('activityColor("error") returns string', typeof activityColor('error') === 'string');
t('activityColor("unknown") returns textDim', activityColor('unknown') === theme.textDim);

// Activity glyphs
t('activityGlyph("tool") = 🔧', activityGlyph('tool') === '🔧');
t('activityGlyph("hive") = 🐝', activityGlyph('hive') === '🐝');
t('activityGlyph("unknown") = •', activityGlyph('unknown') === '•');

// Status
t('statusColor("running") returns running color', statusColor('running') === theme.statusRunning);
t('statusColor("done") returns done color', statusColor('done') === theme.statusDone);
t('statusColor("error") returns error color', statusColor('error') === theme.statusError);

t('statusGlyph("running") = ●', statusGlyph('running') === '●');
t('statusGlyph("done") = ✓', statusGlyph('done') === '✓');
t('statusGlyph("error") = ✕', statusGlyph('error') === '✕');

// Types validation
const activity: ActivityItem = {
    id: '1', number: 1, kind: 'tool', title: 'read_file', status: 'done',
    toolName: 'read_file', summary: 'Read 12 lines', files: ['test.ts'],
    durationMs: 1500,
};
t('ActivityItem shape', activity.kind === 'tool' && activity.status === 'done');

const agent: AgentInfo = {
    id: 'a1', name: 'Researcher', status: 'running', persona: 'RESEARCHER',
    activity: 'Studying TUI patterns', durationMs: 134000,
    toolsUsed: 5, messages: 12,
};
t('AgentInfo shape', agent.name === 'Researcher' && agent.status === 'running');

const task: TaskItem = {
    id: 't1', subject: 'Redesign input composer', status: 'pending',
};
t('TaskItem shape', task.subject.includes('Redesign'));

console.log(`\n═══ RESULT: ${pass} passed | ${fail} failed ═══`);
process.exit(fail > 0 ? 1 : 0);
