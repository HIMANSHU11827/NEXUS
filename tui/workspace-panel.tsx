/** Right-side run inspector for task, live activity, context, and changes. */
import React, {useState} from 'react';
import {Box, Text, useInput} from 'ink';
import {HivePanelBody} from './hive-panel.js';
import {MCPPanelBody, activityKindLabel, mcpServerActive} from './inline-activity.js';
import type {McpServerItem} from './inline-activity.js';
import {TodoPanelBody, WorkspacePanelBody} from './task-list.js';
import {ActivityPanelBody, ApprovalPanelBody, QuestionPanelBody, PlanChecklistRows, PlanPanelBody} from './details-panel.js';
import {phaseDisplayLabel} from './banner.js';
import {
    THEME,
    formatContextPercent,
    formatTokens,
    formatDurationMs,
    compactTaskSubject,
    getFileName,
    statusColor,
    activityColor,
    type ActivityItem,
    type AgentInfo,
    type FileStatus,
    type TimelineEvent,
    type UsageStats,
    type TaskItem,
    type PendingApproval,
    type PendingQuestion,
    type PlanChecklistItem,
    type WorkingPhase
} from './helpers.js';
import {NEXUS_BLUE_BRIGHT, NEXUS_ORANGE_BRIGHT} from './theme.js';

interface NexusWorkspacePanelProps {
    timeline: TimelineEvent[];
    usage: UsageStats;
    mode: string;
    agents: AgentInfo[];
    tasks: TaskItem[];
    touchedFiles: FileStatus[];
    activityItems: ActivityItem[];
    pendingQuestion: PendingQuestion | null;
    pendingApproval?: PendingApproval | null;
    selectedQuestionIndex: number;
    questionCustomMode?: boolean;
    planItems: PlanChecklistItem[];
    planStatus: string;
    planExpanded: boolean;
    mcpConnectedCount: number;
    mcpServers: McpServerItem[];
    selectedActivityId: string | null;
    selectedAgentId: string | null;
    motionFrame: number;
    width: number;
    height: number;
    currentTask?: string;
    isWorking?: boolean;
    workingPhase?: WorkingPhase;
    elapsedMs?: number;
}

const SectionLabel = ({children}: {children: React.ReactNode}) => (
    <Text color="blueBright" bold>{children}</Text>
);

const Divider = ({width}: {width: number}) => (
    <Text color={THEME.borderSoft}>{'─'.repeat(Math.max(1, width - 4))}</Text>
);

const CollapsibleSection = ({
    title,
    shortcut,
    count,
    initiallyExpanded = true,
    children
}: {
    title: string;
    shortcut: string;
    count?: number;
    initiallyExpanded?: boolean;
    children: React.ReactNode;
}) => {
    const [expanded, setExpanded] = useState(initiallyExpanded);
    useInput((input, key) => {
        // Ctrl+H/T/M toggles sections without stealing ordinary composer text.
        if (key.ctrl && input.toLowerCase() === shortcut.toLowerCase()) {
            setExpanded(value => !value);
        }
    });
    return (
        <Box flexDirection="column" marginTop={1}>
            <Text color={NEXUS_BLUE_BRIGHT} bold>{expanded ? '▼' : '▶'} {title}{count !== undefined ? ` ${count}` : ''} <Text color="grey30">[{shortcut}]</Text></Text>
            {expanded && <Box flexDirection="column" marginTop={1}>{children}</Box>}
        </Box>
    );
};

const ContextMeter = ({usage, width}: {usage: UsageStats; width: number}) => {
    if (usage.source !== 'provider') {
        return (
            <Box flexDirection="column">
                <Box justifyContent="space-between">
                    <SectionLabel>CONTEXT</SectionLabel>
                    <Text color="grey">unavailable</Text>
                </Box>
                <Text color="grey">Provider token usage not reported</Text>
            </Box>
        );
    }
    const rawPercent = usage.contextLimit > 0
        ? Math.min(100, (usage.contextTokens / usage.contextLimit) * 100)
        : 0;
    const barWidth = Math.max(8, Math.min(28, width - 10));
    const filledCells = rawPercent > 0 ? Math.max(1, Math.round(rawPercent / 100 * barWidth)) : 0;
    const emptyCells = Math.max(0, barWidth - filledCells);
    const color = rawPercent >= 85 ? 'red' : rawPercent >= 60 ? NEXUS_ORANGE_BRIGHT : 'green';

    return (
        <Box flexDirection="column">
            <Box justifyContent="space-between">
                <SectionLabel>CONTEXT</SectionLabel>
                <Text color={color}>{formatContextPercent(usage.contextTokens, usage.contextLimit)}</Text>
            </Box>
            <Box>
                <Text color={color}>{'█'.repeat(filledCells)}</Text>
                <Text color="grey">{'░'.repeat(emptyCells)}</Text>
            </Box>
            <Text color="grey">
                {formatTokens(usage.contextTokens)} / {formatTokens(usage.contextLimit)} tokens
                {'  '}↑{formatTokens(usage.inputTokens)} ↓{formatTokens(usage.outputTokens)}
            </Text>
        </Box>
    );
};

const fileStatusGlyph = (status: string) => {
    const normalized = status.toLowerCase();
    if (normalized.includes('delete')) return '-';
    if (normalized.includes('create') || normalized.includes('add')) return '+';
    return '~';
};

const WorkspaceSummary = ({
    currentTask,
    isWorking,
    workingPhase,
    elapsedMs,
    activityItems,
    touchedFiles,
    usage,
    width,
    height,
    agents,
    tasks,
    mcpServers,
    selectedAgentId,
    planItems,
    planStatus
}: {
    currentTask: string;
    isWorking: boolean;
    workingPhase: WorkingPhase;
    elapsedMs: number;
    activityItems: ActivityItem[];
    touchedFiles: FileStatus[];
    usage: UsageStats;
    width: number;
    height: number;
    agents: AgentInfo[];
    tasks: TaskItem[];
    mcpServers: McpServerItem[];
    selectedAgentId: string | null;
    planItems: PlanChecklistItem[];
    planStatus: string;
}) => {
    const live = activityItems.find(item => ['running', 'queued', 'pending', 'in_progress', 'working', 'active'].includes(item.status.toLowerCase()));
    const recent = activityItems.slice(0, height >= 30 ? 2 : height >= 22 ? 1 : 0);
    const showContext = height >= 17;
    const showChanges = height >= 25;

    return (
        <Box flexDirection="column" flexGrow={1}>
            <SectionLabel>WORKSPACE</SectionLabel>

            {planItems.length > 0 && (
                <Box flexDirection="column" marginTop={1}>
                    <Box justifyContent="space-between">
                        <Text color={NEXUS_BLUE_BRIGHT} bold>PLAN</Text>
                        <Text color={planStatus === 'failed' ? 'red' : planStatus === 'done' ? 'green' : planStatus === 'blocked' ? NEXUS_ORANGE_BRIGHT : 'grey'}>{planStatus}</Text>
                    </Box>
                    <Box marginTop={1} flexDirection="column">
                        <PlanChecklistRows items={planItems} maxItems={height >= 30 ? 8 : 4} />
                    </Box>
                </Box>
            )}

            {agents.length > 0 && (
                <CollapsibleSection title="HIVE / SUB-AGENTS" shortcut="h" count={agents.length}>
                    <HivePanelBody agents={agents} selectedAgentId={selectedAgentId} tasks={[]} width={Math.max(20, width - 2)} />
                </CollapsibleSection>
            )}

            {tasks.length > 0 && planItems.length === 0 && (
                <CollapsibleSection title="TODO LIST" shortcut="t" count={tasks.length}>
                    <TodoPanelBody tasks={tasks} width={Math.max(20, width - 2)} />
                </CollapsibleSection>
            )}

            {mcpServers.some(mcpServerActive) && (
                <CollapsibleSection title="MCP" shortcut="m" count={mcpServers.filter(mcpServerActive).length}>
                    <MCPPanelBody servers={mcpServers.filter(mcpServerActive)} />
                </CollapsibleSection>
            )}

            {false && <>
            <SectionLabel>ACTIVITY</SectionLabel>
            <Box justifyContent="space-between">
                <Text color={isWorking ? NEXUS_ORANGE_BRIGHT : 'green'} bold>{isWorking ? '● Working' : '● Ready'}</Text>
                {isWorking && elapsedMs > 0 && <Text color="grey">{formatDurationMs(elapsedMs)}</Text>}
            </Box>
            <Text color="grey" wrap="truncate">{live?.title || phaseDisplayLabel(workingPhase)}</Text>
            {recent.map(activity => (
                <Box key={activity.id} marginTop={1} flexDirection="column">
                    <Box justifyContent="space-between">
                        <Text color={activity.logoColor || activityColor(activity.kind)} bold>{activityKindLabel(activity.kind)}</Text>
                        <Text color={statusColor(activity.status)}>{activity.status.toUpperCase()}</Text>
                    </Box>
                    <Text color="grey" wrap="truncate">{compactTaskSubject(activity.summary || activity.title || activity.toolName || 'activity', Math.max(12, width - 6))}</Text>
                </Box>
            ))}
            </>}

            {showContext && <><Box marginY={0}><Divider width={width} /></Box><ContextMeter usage={usage} width={width} /></>}

            {showChanges && <>
                <Box marginY={1}><Divider width={width} /></Box>
                <SectionLabel>CHANGES</SectionLabel>
                {touchedFiles.length === 0 ? (
                    <Text color="grey">No files changed yet</Text>
                ) : (
                    touchedFiles.slice(0, Math.max(1, Math.min(8, height - 24))).map(file => (
                    <Box key={file.name} justifyContent="space-between">
                        <Box>
                            <Text color={fileStatusGlyph(file.status) === '-' ? 'red' : 'green'}>{fileStatusGlyph(file.status)} </Text>
                            <Text color="grey" wrap="truncate">{getFileName(file.name)}</Text>
                        </Box>
                        {(file.additions != null || file.deletions != null) && (
                            <Box>
                                {file.additions != null && <Text color="green">+{file.additions}</Text>}
                                {file.deletions != null && <Text color="red"> -{file.deletions}</Text>}
                            </Box>
                        )}
                    </Box>
                    ))
                )}
                {touchedFiles.length > 0 && <Text color="grey">{touchedFiles.length} file{touchedFiles.length === 1 ? '' : 's'} changed</Text>}
            </>}
        </Box>
    );
};

export const NexusWorkspacePanel = React.memo(({
    usage,
    mode,
    agents,
    tasks,
    touchedFiles,
    activityItems,
    pendingQuestion,
    pendingApproval,
    selectedQuestionIndex,
    questionCustomMode,
    planItems,
    planStatus,
    planExpanded,
    mcpServers,
    selectedActivityId,
    selectedAgentId,
    width,
    height,
    currentTask = '',
    isWorking = false,
    workingPhase = 'thinking',
    elapsedMs = 0
}: NexusWorkspacePanelProps & {
    voiceMode: 'off' | 'auto' | 'manual' | 'text';
    voicePhase: string;
    voiceTranscriptPreview: string;
    voiceReplyPreview: string;
}) => {
    const selectedActivity = activityItems.find(activity => activity.id === selectedActivityId) || activityItems[0] || null;

    return (
        <Box
            flexDirection="column"
            width={width}
            height={height}
            borderStyle="single"
            borderColor={THEME.borderSoft}
            paddingX={1}
            paddingY={1}
            backgroundColor={THEME.panelBg}
        >
            {mode === 'workspace' ? (
                <WorkspaceSummary
                    currentTask={currentTask}
                    isWorking={isWorking}
                    workingPhase={workingPhase}
                    elapsedMs={elapsedMs}
                    activityItems={activityItems}
                    touchedFiles={touchedFiles}
                    agents={agents}
                    tasks={tasks}
                    mcpServers={mcpServers}
                    selectedAgentId={selectedAgentId}
                    planItems={planItems}
                    planStatus={planStatus}
                    usage={usage}
                    width={width}
                    height={height}
                />
            ) : (
                <Box flexDirection="column" flexGrow={1}>
                    <Box justifyContent="space-between" marginBottom={1}>
                        <Text bold color={NEXUS_BLUE_BRIGHT}>NEXUS</Text>
                        <Text color="blueBright" bold>{mode.toUpperCase()}</Text>
                    </Box>
                    {mode === 'approval' ? (
                        <ApprovalPanelBody approval={pendingApproval || null} width={width} />
                    ) : mode === 'question' ? (
                        <QuestionPanelBody question={pendingQuestion} selectedIndex={selectedQuestionIndex} customActive={questionCustomMode === true} width={width} />
                    ) : mode === 'plan' ? (
                        <PlanPanelBody items={planItems} status={planStatus} expanded={planExpanded} />
                    ) : mode === 'hive' || mode === 'agent' ? (
                        <HivePanelBody agents={agents} selectedAgentId={mode === 'agent' ? selectedAgentId : null} tasks={tasks} width={width} />
                    ) : mode === 'activity' ? (
                        <ActivityPanelBody activity={selectedActivity} width={width} />
                    ) : mode === 'mcp' ? (
                        <MCPPanelBody servers={mcpServers} />
                    ) : (
                        <WorkspacePanelBody tasks={tasks} agents={agents} selectedAgentId={selectedAgentId} width={width} />
                    )}
                </Box>
            )}
        </Box>
    );
});
