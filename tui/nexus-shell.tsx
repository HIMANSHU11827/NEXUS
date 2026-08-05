/**
 * Nexus TUI v3.0 — Status + Hive + Activity Wrapper
 * Integrates new components into the existing TUI by wrapping
 * the App component's render output with StatusBar and enhanced panels.
 *
 * This is a progressive upgrade — the existing nexus-tui.tsx still
 * contains all the core logic; this module adds the new UI layers.
 */
import React from 'react';
import {Box, Text} from 'ink';
import type {AgentInfo, TaskItem, UsageInfo, SandboxTier, PermissionMode} from './types.js';
import {StatusBar} from './status-bar.js';
import {HivePanelBody} from './hive-panel.js';
import {getTheme} from './theme.js';
import {ActivityCard} from './activity-card.js';

/** Status bar props for the bottom bar */
export interface NexusStatusProps {
    model: string;
    tokens: number;
    cost: number;
    contextWindow: number;
    inputTokens: number;
    outputTokens: number;
    sandboxTier: SandboxTier;
    permissionMode: PermissionMode;
    voiceMode: string;
    voicePhase: string;
    mcpCount: number;
    agentCount: number;
    taskCount: number;
}

/** Wraps children with the Nexus status bar at the bottom */
export const NexusShell: React.FC<{
    status: NexusStatusProps;
    children: React.ReactNode;
}> = ({status, children}) => {
    const usage: UsageInfo = {
        model: status.model,
        tokens: status.inputTokens + status.outputTokens,
        cost: status.cost,
        contextWindow: status.contextWindow,
        inputTokens: status.inputTokens,
        outputTokens: status.outputTokens,
    };

    return (
        <Box flexDirection="column" flexGrow={1}>
            {/* Main content */}
            <Box flexGrow={1}>{children}</Box>

            {/* Status bar */}
            <StatusBar
                usage={usage}
                sandboxTier={status.sandboxTier}
                permissionMode={status.permissionMode}
                voiceMode={status.voiceMode}
                voicePhase={status.voicePhase}
                mcpCount={status.mcpCount}
                agentCount={status.agentCount}
                taskCount={status.taskCount}
            />
        </Box>
    );
};

/** Enhanced hive panel wrapper */
export const EnhancedHivePanel: React.FC<{
    agents: AgentInfo[];
    selectedAgentId: string | null;
    tasks: TaskItem[];
    onClose: () => void;
}> = ({agents, selectedAgentId, tasks, onClose}) => {
    return (
        <Box flexDirection="column" flexGrow={1} paddingX={1}>
            <HivePanelBody agents={agents} selectedAgentId={selectedAgentId} tasks={tasks} />
        </Box>
    );
};

/** Activity list using the new card component */
export const EnhancedActivityList: React.FC<{
    activities: Array<any>;
    width: number;
    maxItems?: number;
}> = ({activities, width, maxItems = 20}) => {
    const theme = getTheme();

    if (!activities || activities.length === 0) {
        return (
            <Box paddingX={1}>
                <Text color={theme.textMuted}>No activities yet</Text>
            </Box>
        );
    }

    const visible = activities.slice(0, maxItems);

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box paddingX={1} marginBottom={1}>
                <Text color="white" bold>⚡ Activity ({activities.length})</Text>
            </Box>
            {visible.map((activity, i) => (
                <Box key={activity.id || i} paddingX={1}>
                    <ActivityCard activity={activity} width={width - 2} index={i} />
                </Box>
            ))}
            {activities.length > maxItems && (
                <Box paddingX={1}>
                    <Text color={theme.textMuted}>... and {activities.length - maxItems} more activities</Text>
                </Box>
            )}
        </Box>
    );
};

/** Simple streaming indicator */
export const StreamingIndicator: React.FC<{
    isStreaming: boolean;
    phase?: string;
}> = ({isStreaming, phase}) => {
    const theme = getTheme();
    if (!isStreaming) return null;
    return (
        <Box paddingX={1}>
            <Text color={theme.primary}>▌ {phase || 'generating...'}</Text>
        </Box>
    );
};
