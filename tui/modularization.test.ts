/**
 * Nexus TUI v3.0 — Modularization Check
 * Test-only guard ensuring nexus-tui.tsx stays modular: the monolith must be
 * meaningfully smaller than the pre-refactor baseline and the extracted
 * modules must exist and export their expected symbols.
 */
import {readFileSync, existsSync} from 'node:fs';

const MONOLITH_BASELINE_LINES = 5059; // pre-refactor size
const MONOLITH_MAX_LINES = 4000;      // must have shrunk by extraction

let pass = 0, fail = 0;
function t(label: string, ok: boolean) {
    if (ok) { pass++; console.log(`  ✅ ${label}`); }
    else { fail++; console.log(`  ❌ ${label}`); }
}

console.log('═══ Nexus TUI v3.0 — Modularization Check ═══\n');

function read(name: string): string {
    if (!existsSync(name)) return '';
    return readFileSync(name, 'utf8');
}

const monolith = read('nexus-tui.tsx');
const monolithLines = monolith.replace(/\n$/, '').split('\n').length;

t(`nexus-tui.tsx is ${monolithLines} lines (baseline ${MONOLITH_BASELINE_LINES})`, monolithLines < MONOLITH_BASELINE_LINES);
t(`nexus-tui.tsx shrank below ${MONOLITH_MAX_LINES} lines`, monolithLines < MONOLITH_MAX_LINES);

// Extracted pure-helper module
const helpers = read('helpers.ts');
t('helpers.ts exists and is non-empty', helpers.length > 1000);
t('helpers.ts exports adaptCanonicalEvent', helpers.includes('export const adaptCanonicalEvent'));
t('helpers.ts exports withActivityIdentity', helpers.includes('export const withActivityIdentity'));
t('helpers.ts consumes the server command registry', helpers.includes('export const normalizeCommandRegistry'));
t('helpers.ts has no hard-coded command catalog', !helpers.includes('export const COMMANDS = ['));

// Extracted view modules
const chatView = read('chat-view.tsx');
t('chat-view.tsx exports buildChatLines', chatView.includes('export const buildChatLines'));
t('chat-view.tsx exports ChatLineView', chatView.includes('export const ChatLineView'));

const taskList = read('task-list.tsx');
t('task-list.tsx exports TodoPanelBody', taskList.includes('export const TodoPanelBody'));
t('task-list.tsx uses taskStateGlyph', taskList.includes('taskStateGlyph'));

const banner = read('banner.tsx');
t('banner.tsx exports NexusBanner', banner.includes('export const NexusBanner'));
t('banner.tsx exports WorkingStatus', banner.includes('export const WorkingStatus'));

const welcomeLogo = read('welcome-logo.tsx');
t('welcome-logo.tsx exports NexusWelcomeLogo', welcomeLogo.includes('export const NexusWelcomeLogo'));

const commandPalette = read('command-palette.tsx');
t('command-palette.tsx exports CommandPalette', commandPalette.includes('export const CommandPalette'));

const detailsPanel = read('details-panel.tsx');
t('details-panel.tsx exports QuestionPanelBody', detailsPanel.includes('export const QuestionPanelBody'));
t('details-panel.tsx exports PlanPanelBody', detailsPanel.includes('export const PlanPanelBody'));

const workspacePanel = read('workspace-panel.tsx');
t('workspace-panel.tsx exports NexusWorkspacePanel', workspacePanel.includes('export const NexusWorkspacePanel'));

// The orchestrator must import from the extracted modules instead of redefining them.
t('nexus-tui.tsx imports from helpers.js', monolith.includes("from './helpers.js'"));
t('nexus-tui.tsx imports from chat-view.js', monolith.includes("from './chat-view.js'"));
t('nexus-tui.tsx imports from banner.js', monolith.includes("from './banner.js'"));
t('nexus-tui.tsx does not render the removed top banner', !monolith.includes('<NexusBanner'));
t('nexus-tui.tsx imports the welcome logo', monolith.includes("from './welcome-logo.js'"));
t('nexus-tui.tsx loads commands from the server registry', monolith.includes('`${API_BASE}/commands`'));
t('nexus-tui.tsx delegates registered fallbacks to shared execution', monolith.includes("postJson('/command'"));
t('nexus-tui.tsx no longer defines ChatLineView', !monolith.includes('const ChatLineView = React.memo'));
t('nexus-tui.tsx no longer defines NexusWorkspacePanel', !monolith.includes('const NexusWorkspacePanel = React.memo'));

// The SSE/startup contract must be preserved in the orchestrator.
t('keeps SSE message unwrap contract', monolith.includes('payload.content ?? payload.data ?? raw'));
t('keeps done-before-parse SSE ordering', monolith.indexOf("if (eventType === 'done')") < monolith.indexOf('let payload: any;'));
t('keeps INITIAL_HISTORY', monolith.includes('INITIAL_HISTORY'));

console.log(`\n═══ RESULT: ${pass} passed | ${fail} failed ═══`);
process.exit(fail > 0 ? 1 : 0);
