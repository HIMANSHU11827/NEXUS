import React from 'react';
import {PassThrough} from 'node:stream';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {Box, render} from 'ink';
import chalk from 'chalk';
import {NexusBanner, WorkingStatus} from './banner.js';
import {ChatLineView, buildChatLines} from './chat-view.js';
import {InputComposer} from './input-composer.js';
import {StatusBar} from './status-bar.js';
import {NexusWorkspacePanel} from './workspace-panel.js';
import {resolveTuiLayout} from './layout.js';
import {THEME, type ActivityItem, type Message} from './helpers.js';

const WIDTH = 160;
const HEIGHT = 44;
chalk.level = 3;

const activities: ActivityItem[] = [
    {
        id: 'terminal', number: 5, kind: 'terminal', title: 'Running terminal command',
        summary: 'npm test -- provider fallback', status: 'running', toolName: 'terminal',
        command: 'npm test -- provider fallback', startedAt: Date.now() - 18000
    },
    {
        id: 'hive', number: 4, kind: 'hive', title: 'Reviewing fallback behavior',
        summary: 'Testing agent · checking edge cases', status: 'running', toolName: 'testing-agent',
        startedAt: Date.now() - 12000
    },
    {
        id: 'mcp', number: 7, kind: 'mcp', title: 'Searching repository context',
        summary: 'fallback', status: 'done', toolName: 'mcp__github__search_code', durationMs: 610
    },
    {
        id: 'skill', number: 6, kind: 'skill', title: 'Reviewing the patch',
        summary: 'Review changes', status: 'done', toolName: 'skill__code_review', durationMs: 390
    },
    {
        id: 'file', number: 3, kind: 'file', title: 'Edited a file',
        summary: 'providers/fallback.ts', status: 'done', toolName: 'apply_patch',
        files: ['providers/fallback.ts'], operation: 'edit', durationMs: 840
    },
    {
        id: 'reading', number: 9, kind: 'file', title: 'Read a file',
        summary: 'C:\\workspace\\src\\providers\\provider-config.ts', status: 'done', toolName: 'reading',
        files: ['C:\\workspace\\src\\providers\\provider-config.ts'], operation: 'read', durationMs: 8000
    },
    {
        id: 'search', number: 2, kind: 'search', title: 'Searched files',
        summary: 'provider retry and backoff rules', status: 'done', toolName: 'code_search', durationMs: 420
    },
    {
        id: 'search-fail', number: 8, kind: 'search', title: 'Search unavailable',
        summary: 'legacy provider endpoint', status: 'failed', toolName: 'web_search',
        error: 'Search provider unavailable', durationMs: 1100
    },
    {
        id: 'plan', number: 1, kind: 'plan', title: 'Advanced Planning',
        summary: '4 steps', status: 'done', toolName: 'plan',
        detail: '1. Inspect fallback router\n2. Improve retry classification\n3. Add tests\n4. Verify', durationMs: 180
    }
];

const history: Message[] = [
    {role: 'user', content: 'Improve the provider fallback flow'},
    {role: 'assistant', content: 'Got it. I’ll inspect the current fallback logic, strengthen error classification, and verify the behavior with focused tests.'},
    {role: 'activity', content: 'Plan ready', activityId: 'plan'},
    {role: 'activity', content: 'Search failed', activityId: 'search-fail'},
    {role: 'activity', content: 'Search complete', activityId: 'search'},
    {role: 'activity', content: 'File updated', activityId: 'file'},
    {role: 'activity', content: 'File read', activityId: 'reading'},
    {role: 'activity', content: 'Skill complete', activityId: 'skill'},
    {role: 'activity', content: 'MCP complete', activityId: 'mcp'},
    {role: 'activity', content: 'Hive agent working', activityId: 'hive'},
    {role: 'activity', content: 'Terminal running', activityId: 'terminal'}
];

const Preview = () => {
    const layout = resolveTuiLayout(WIDTH, HEIGHT);
    const chatLines = buildChatLines(history, activities, layout.chatContentWidth, 'file', 'file', false);
    return (
        <Box width={WIDTH} height={HEIGHT} flexDirection="row" backgroundColor={THEME.appBg}>
            <Box width={layout.mainWidth} height={HEIGHT} flexDirection="column" backgroundColor={THEME.panelAltBg}>
                <NexusBanner
                    width={layout.chatContentWidth}
                    isWorking
                    phase="verifying"
                    runId="7f4c2a1d"
                    elapsedMs={134000}
                    connectionState="online"
                />
                <Box width={layout.chatContentWidth + 2} height={layout.chatViewportHeight} paddingX={1} flexDirection="column">
                    {chatLines.map(line => <ChatLineView key={line.key} line={line} width={layout.chatContentWidth} frame={3} />)}
                    <WorkingStatus
                        frame={3}
                        width={layout.chatContentWidth}
                        phase="verifying"
                        activity={activities[0]}
                        elapsedMs={134000}
                    />
                </Box>
                <InputComposer value="" onChange={() => {}} onSubmit={() => {}} placeholder="Message NEXUS..." isBusy showHints width={layout.mainWidth} />
                <StatusBar
                    width={layout.mainWidth}
                    usage={{tokens: 2300, inputTokens: 1100, outputTokens: 1200, contextWindow: 8000, model: 'gpt-4.1'}}
                    sandboxTier="normal"
                    permissionMode="auto"
                    voiceMode="off"
                    voicePhase="off"
                    mcpCount={2}
                    agentCount={1}
                    taskCount={1}
                    activeTool="terminal"
                    connectionState="online"
                />
            </Box>
            <NexusWorkspacePanel
                timeline={[]}
                usage={{contextTokens: 2300, contextLimit: 8000, inputTokens: 1100, outputTokens: 1200}}
                mode="workspace"
                agents={[]}
                tasks={[]}
                touchedFiles={[
                    {name: 'C:\\Users\\himan\\Desktop\\NEXUS AI\\providers\\fallback.ts', status: 'MODIFIED', additions: 34, deletions: 6},
                    {name: 'C:\\Users\\himan\\Desktop\\NEXUS AI\\tests\\fallback.test.ts', status: 'MODIFIED', additions: 86, deletions: 0}
                ]}
                activityItems={activities}
                pendingQuestion={null}
                selectedQuestionIndex={0}
                planItems={[]}
                planStatus="planning"
                planExpanded={false}
                mcpConnectedCount={2}
                mcpServers={[]}
                selectedActivityId="terminal"
                selectedAgentId={null}
                motionFrame={3}
                voiceMode="off"
                voicePhase="off"
                voiceTranscriptPreview=""
                voiceReplyPreview=""
                width={layout.sidebarWidth}
                height={HEIGHT}
                currentTask="Improve the provider fallback flow"
                isWorking
                workingPhase="verifying"
                elapsedMs={134000}
            />
        </Box>
    );
};

const output = new PassThrough() as PassThrough & {
    columns: number;
    rows: number;
    isTTY: boolean;
    getColorDepth: () => number;
    hasColors: () => boolean;
};
output.columns = WIDTH;
output.rows = HEIGHT;
output.isTTY = true;
output.getColorDepth = () => 24;
output.hasColors = () => true;
const input = new PassThrough() as PassThrough & {
    isTTY: boolean;
    isRaw: boolean;
    setRawMode: (mode: boolean) => PassThrough;
    ref: () => PassThrough;
    unref: () => PassThrough;
};
input.isTTY = true;
input.isRaw = false;
input.setRawMode = (mode: boolean) => {
    input.isRaw = mode;
    return input;
};
input.ref = () => input;
input.unref = () => input;
const chunks: Buffer[] = [];
output.on('data', chunk => chunks.push(Buffer.from(chunk)));

const instance = render(<Preview />, {
    stdout: output as unknown as NodeJS.WriteStream,
    stdin: input as unknown as NodeJS.ReadStream,
    interactive: false,
    patchConsole: false,
    exitOnCtrlC: false
});
await instance.waitUntilRenderFlush();
instance.unmount();
await instance.waitUntilExit();

const artifactDir = path.join(process.cwd(), 'artifacts');
await mkdir(artifactDir, {recursive: true});
const outputPath = path.join(artifactDir, 'tui-redesign-frame.ansi');
await writeFile(outputPath, Buffer.concat(chunks));
process.stdout.write(`${outputPath}\n`);
