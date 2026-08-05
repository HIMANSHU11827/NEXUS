/**
 * Nexus TUI v3.0 — Workspace Sidebar Panel
 * Right-hand panel: context meter, activity rail, and mode-switching bodies
 * (question, plan, hive, activity, mcp, workspace).
 */
import React from 'react';
import {Box, Text} from 'ink';
import {HivePanelBody} from './hive-panel.js';
import {MCPPanelBody} from './inline-activity.js';
import type {McpServerItem} from './inline-activity.js';
import {TodoPanelBody, WorkspacePanelBody} from './task-list.js';
import {ActivityPanelBody, QuestionPanelBody, PlanPanelBody} from './details-panel.js';
import {
    THEME,
    CONTEXT_BAR_WIDTH,
    MAX_TIMELINE_ITEMS,
    formatContextPercent,
    formatTokens,
    formatDurationMs,
    compactTaskSubject,
    timelineColor,
    timelineGlyph,
    statusColor,
    activityStatusGlyph,
    activityColor,
    activityGlyph,
    type ActivityItem,
    type AgentInfo,
    type TimelineEvent,
    type UsageStats,
    type TaskItem,
    type PendingQuestion
} from './helpers.js';

interface NexusWorkspacePanelProps {
    timeline: TimelineEvent[];
    usage: UsageStats;
    mode: string;
    agents: AgentInfo[];
    tasks: TaskItem[];
    touchedFiles: Array<{name: string; status: string}>;
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
}

const ContextMeter = React.memo(({usage}: {usage: UsageStats}) => {
    const rawPercent = usage.contextLimit > 0 ? Math.min(100, (usage.contextTokens / usage.contextLimit) * 100) : 0;
    const filledCells = rawPercent > 0
        ? Math.max(1, Math.min(CONTEXT_BAR_WIDTH, Math.round((rawPercent / 100) * CONTEXT_BAR_WIDTH)))
        : 0;
    const emptyCells = CONTEXT_BAR_WIDTH - filledCells;
    const contextLabel = formatContextPercent(usage.contextTokens, usage.contextLimit);
    const contextColor = rawPercent >= 85 ? 'red' : rawPercent >= 60 ? 'yellow' : 'green';

    return (
        <Box flexDirection="column" marginBottom={1}>
            <Box justifyContent="space-between">
                <Text color="white" bold>Context</Text>
                <Text color={contextColor}>{contextLabel}</Text>
            </Box>

            <Box>
                <Text color={contextColor}>{'█'.repeat(filledCells)}</Text>
                <Text color="grey30">{'░'.repeat(emptyCells)}</Text>
            </Box>

            <Box>
                <Text color="grey">Tokens </Text>
                <Text color="grey30">↑ </Text>
                <Text color="grey">{formatTokens(usage.inputTokens)} </Text>
                <Text color="grey30">↓ </Text>
                <Text color="grey">{formatTokens(usage.outputTokens)}</Text>
                <Text color="grey30"> · total </Text>
                <Text color="grey">{formatTokens(usage.contextTokens)}</Text>
            </Box>
        </Box>
    );
});

const ActivityRail = React.memo(({
    timeline,
    activityItems,
    selectedActivityId,
    motionFrame
}: {
    timeline: TimelineEvent[];
    activityItems: ActivityItem[];
    selectedActivityId: string | null;
    motionFrame: number;
}) => {
    if (activityItems.length === 0) return null;

    const visibleTimeline = timeline.length > 0 ? timeline.slice(-MAX_TIMELINE_ITEMS) : [
        {kind: 'step' as const, weight: 1, label: 'Session ready'}
    ];
    const activityEvents = visibleTimeline.slice(-CONTEXT_BAR_WIDTH);
    const latestEvent = activityEvents[activityEvents.length - 1];
    const running = activityItems.find(activity =>
        ['running', 'queued', 'pending', 'in_progress', 'working'].includes(activity.status.toLowerCase())
    );
    const latestActivity = running || activityItems[0] || null;
    const activityLabel = latestActivity
        ? compactTaskSubject(`${latestActivity.toolName || latestActivity.kind} ${latestActivity.status}`, 24)
        : compactTaskSubject(latestEvent?.label || 'Session ready', 24);
    const railMarker = (index: number, event: TimelineEvent) => {
        const isLatest = index === activityEvents.length - 1;
        if (isLatest && running) return ['●', running.logoColor || activityColor(running.kind)] as const;
        if (isLatest) return ['●', timelineColor(event.kind)] as const;
        return [timelineGlyph(event), timelineColor(event.kind)] as const;
    };
    const rows = activityItems.slice(0, 5);

    return (
        <Box flexDirection="column" marginBottom={1}>
            <Box justifyContent="space-between">
                <Text color="white" bold>Activity</Text>
                <Text color={latestActivity ? (latestActivity.logoColor || activityColor(latestActivity.kind)) : timelineColor(latestEvent.kind)}>
                    {activityLabel}
                </Text>
            </Box>
            <Box>
                <Text color="grey30">╺</Text>
                {activityEvents.map((event, index) => {
                    const [glyph, color] = railMarker(index, event);
                    return (
                        <Text key={`${event.kind}-${event.label}-${index}`} color={color}>
                            {glyph}
                        </Text>
                    );
                })}
                <Text color="grey30">{'─'.repeat(Math.max(0, CONTEXT_BAR_WIDTH - activityEvents.length))}╸</Text>
            </Box>

            {rows.length > 0 ? (
                <Box flexDirection="column" marginTop={1}>
                    {rows.map((activity, index) => {
                        const selected = activity.id === selectedActivityId;
                        const isRunning = ['running', 'queued', 'pending', 'in_progress', 'working'].includes(activity.status.toLowerCase());
                        const pulse = isRunning ? ['·', '∙', '•'][motionFrame % 3] : activityStatusGlyph(activity.status);
                        const duration = formatDurationMs(activity.durationMs);
                        const label = compactTaskSubject(activity.summary || activity.title || activity.toolName || activity.kind, 28);
                        return (
                            <Box key={activity.id} marginTop={index === 0 ? 0 : 1}>
                                <Box width={3}>
                                    <Text color={selected ? 'white' : activity.logoColor || activityColor(activity.kind)} bold={selected}>
                                        {selected ? '›' : ' '}{activity.logo || activityGlyph(activity.kind)}
                                    </Text>
                                </Box>
                                <Box flexDirection="column" flexGrow={1}>
                                    <Box justifyContent="space-between">
                                        <Text color={selected ? 'white' : 'grey'} bold={selected}>{activity.toolName || activity.kind}</Text>
                                        <Text color={statusColor(activity.status)}>{pulse} {activity.status}</Text>
                                    </Box>
                                    <Text color="grey30" wrap="truncate">
                                        {label}{duration ? ` · ${duration}` : ''}
                                    </Text>
                                </Box>
                            </Box>
                        );
                    })}
                </Box>
            ) : null}
        </Box>
    );
});

export const NexusWorkspacePanel = React.memo((({
    timeline,
    usage,
    mode,
    agents,
    tasks,
    activityItems,
    pendingQuestion,
    selectedQuestionIndex,
    questionCustomMode,
    planItems,
    planStatus,
    planExpanded,
    mcpConnectedCount,
    mcpServers,
    selectedActivityId,
    selectedAgentId,
    width,
    height,
    voiceMode,
    voicePhase,
    voiceTranscriptPreview,
    voiceReplyPreview,
    motionFrame
}: NexusWorkspacePanelProps & {
    voiceMode: 'off' | 'auto' | 'manual' | 'text';
    voicePhase: string;
    voiceTranscriptPreview: string;
    voiceReplyPreview: string;
}) => {
    const selectedActivity = activityItems.find(activity => activity.id === selectedActivityId) || null;
    const backgroundTaskCount = tasks.filter(task =>
        ['active', 'running', 'working', 'in_progress', 'background'].includes(task.status.toLowerCase())
    ).length;
    const activeHiveCount = agents.filter(agent =>
        ['active', 'running', 'working', 'busy', 'spawned'].includes(agent.status.toLowerCase())
    ).length;

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
            <Box marginBottom={1}>
                <Text bold color="white">🐝 NEXUS</Text>
            </Box>

            <ContextMeter usage={usage} />

            <ActivityRail
                timeline={timeline}
                activityItems={activityItems}
                selectedActivityId={selectedActivityId}
                motionFrame={motionFrame}
            />

            {(backgroundTaskCount > 0 || mcpConnectedCount > 0 || activeHiveCount > 0) && (
                <Box flexDirection="column" marginBottom={1}>
                    {backgroundTaskCount > 0 && <Text color="cyan">Background tasks  {backgroundTaskCount}</Text>}
                    {mcpConnectedCount > 0 && <Text color="magentaBright">MCP connected     {mcpConnectedCount}</Text>}
                    {activeHiveCount > 0 && <Text color="blueBright">Hive agents       {activeHiveCount}</Text>}
                </Box>
            )}

            {mode === 'question' ? (
                <QuestionPanelBody question={pendingQuestion} selectedIndex={selectedQuestionIndex} customActive={questionCustomMode === true} />
            ) : mode === 'plan' ? (
                <PlanPanelBody items={planItems} status={planStatus} expanded={planExpanded} />
            ) : mode === 'hive' || mode === 'agent' ? (
                <HivePanelBody agents={agents} selectedAgentId={mode === 'agent' ? selectedAgentId : null} tasks={tasks} width={width} />
            ) : mode === 'activity' ? (
                <ActivityPanelBody activity={selectedActivity} width={width} />
            ) : mode === 'mcp' ? (
                <MCPPanelBody servers={mcpServers} />
            ) : (
                <WorkspacePanelBody
                    tasks={tasks}
                    agents={agents}
                    selectedAgentId={selectedAgentId}
                    width={width}
                />
            )}
        </Box>
    );
}));