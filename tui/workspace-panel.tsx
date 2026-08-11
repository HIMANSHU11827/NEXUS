/** Right-side run inspector for task, live activity, context, and changes. */
import React from 'react';
import {Box, Text} from 'ink';
import {HivePanelBody} from './hive-panel.js';
import {MCPPanelBody, activityKindLabel} from './inline-activity.js';
import type {McpServerItem} from './inline-activity.js';
import {WorkspacePanelBody} from './task-list.js';
import {ActivityPanelBody, QuestionPanelBody, PlanPanelBody} from './details-panel.js';
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
    type PendingQuestion,
    type WorkingPhase
} from './helpers.js';

interface NexusWorkspacePanelProps {
    timeline: TimelineEvent[];
    usage: UsageStats;
    mode: string;
    agents: AgentInfo[];
    tasks: TaskItem[];
    touchedFiles: FileStatus[];
    activityItems: ActivityItem[];
    pendingQuestion: PendingQuestion | null;
    selectedQuestionIndex: number;
    questionCustomMode?: boolean;
    planItems: string[];
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

const ContextMeter = ({usage, width}: {usage: UsageStats; width: number}) => {
    const rawPercent = usage.contextLimit > 0
        ? Math.min(100, (usage.contextTokens / usage.contextLimit) * 100)
        : 0;
    const barWidth = Math.max(8, Math.min(28, width - 10));
    const filledCells = rawPercent > 0 ? Math.max(1, Math.round(rawPercent / 100 * barWidth)) : 0;
    const emptyCells = Math.max(0, barWidth - filledCells);
    const color = rawPercent >= 85 ? 'red' : rawPercent >= 60 ? 'yellow' : 'green';

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
    height
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
}) => {
    const live = activityItems.find(item => ['running', 'queued', 'pending', 'in_progress', 'working', 'active'].includes(item.status.toLowerCase()));
    const recent = activityItems.slice(0, height >= 30 ? 2 : height >= 22 ? 1 : 0);
    const showContext = height >= 17;
    const showChanges = height >= 25;

    return (
        <Box flexDirection="column" flexGrow={1}>
            <SectionLabel>TASK</SectionLabel>
            <Text color="white" wrap={height < 22 ? 'truncate' : 'wrap'}>{currentTask || 'Ready for your next instruction'}</Text>

            <Box marginY={1}><Divider width={width} /></Box>

            <SectionLabel>ACTIVITY</SectionLabel>
            <Box justifyContent="space-between">
                <Text color={isWorking ? 'yellowBright' : 'green'} bold>{isWorking ? '● Working' : '● Ready'}</Text>
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

            {showContext && <><Box marginY={1}><Divider width={width} /></Box><ContextMeter usage={usage} width={width} /></>}

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
                                <Text color="green">+{file.additions || 0}</Text>
                                <Text color="red"> -{file.deletions || 0}</Text>
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
                    usage={usage}
                    width={width}
                    height={height}
                />
            ) : (
                <Box flexDirection="column" flexGrow={1}>
                    <Box justifyContent="space-between" marginBottom={1}>
                        <Text bold color="cyanBright">NEXUS</Text>
                        <Text color="blueBright" bold>{mode.toUpperCase()}</Text>
                    </Box>
                    {mode === 'question' ? (
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
