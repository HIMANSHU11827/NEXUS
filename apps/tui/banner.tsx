/** Compact run header and honest live-work status. */
import React from 'react';
import {Box, Text} from 'ink';
import {voicePhaseColor, WORKING_STATES, THEME, type ActivityItem, type WorkingPhase} from './helpers.js';
import {NEXUS_BLUE_BRIGHT, NEXUS_ORANGE, NEXUS_ORANGE_BRIGHT} from './theme.js';

const formatElapsed = (elapsedMs = 0) => {
    const totalSeconds = Math.max(0, Math.floor(elapsedMs / 1000));
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return minutes > 0 ? `${minutes}m ${String(seconds).padStart(2, '0')}s` : `${seconds}s`;
};

export const phaseDisplayLabel = (phase: WorkingPhase): string => {
    const labels: Record<WorkingPhase, string> = {
        thinking: 'Reasoning about the next action',
        querying: 'Contacting the model',
        streaming: 'Writing the response',
        tool: 'Running a tool',
        skill: 'Applying a skill',
        plugin: 'Loading a plugin',
        mcp: 'Calling an MCP server',
        hive: 'Coordinating Hive agents',
        config: 'Updating configuration',
        settings: 'Updating settings',
        compact: 'Compacting context',
        evolution: 'Running evolution work',
        self_improvement: 'Running self-improvement',
        knowledge: 'Retrieving knowledge',
        memory: 'Reading memory',
        no_planning: 'Choosing the next action',
        simple_planning: 'Building a plan',
        advance_planning: 'Decomposing the task',
        auditing: 'Reviewing the work',
        verifying: 'Running verification',
        working: 'Running a command'
    };
    return labels[phase];
};

interface NexusBannerProps {
    width: number;
    isWorking?: boolean;
    phase?: WorkingPhase;
    runId?: string | null;
    elapsedMs?: number;
    connectionState?: 'connecting' | 'online' | 'offline';
}

export const NexusBanner = React.memo(({
    width,
    isWorking = false,
    phase = 'thinking',
    runId,
    elapsedMs = 0,
    connectionState = 'online'
}: NexusBannerProps) => {
    const stateColor = connectionState === 'offline' ? 'red' : isWorking ? NEXUS_ORANGE_BRIGHT : connectionState === 'connecting' ? NEXUS_ORANGE : 'green';
    const stateLabel = connectionState === 'offline' ? 'Offline' : isWorking ? 'Working' : connectionState === 'connecting' ? 'Connecting' : 'Ready';
    const compact = width < 64;
    const tiny = width < 34;
    const runLabel = runId ? runId.slice(-8) : '';

    return (
        <Box height={3} paddingX={1} borderStyle="single" borderColor={THEME.borderSoft} justifyContent="space-between">
            <Box>
                <Text bold color={NEXUS_BLUE_BRIGHT}>{tiny ? 'NX' : 'NEXUS'}</Text>
                {!tiny && <Text color="grey">  |  </Text>}
                <Text color={stateColor}>{tiny ? ' ' : ''}● {stateLabel}</Text>
                {!compact && isWorking && <Text color="grey">  ·  {phaseDisplayLabel(phase)}</Text>}
                {!compact && runLabel && <Text color="grey">  |  Run {runLabel}</Text>}
                {!compact && isWorking && elapsedMs >= 1000 && <Text color="grey">  ·  {formatElapsed(elapsedMs)}</Text>}
            </Box>
            {!tiny && <Box>
                <Text color="grey">{width < 48 ? 'Esc' : 'Esc stop'}</Text>
            </Box>}
        </Box>
    );
});

export const WorkingStatus = React.memo(({
    frame,
    width,
    phase,
    activity,
    elapsedMs = 0
}: {
    frame: number;
    width: number;
    phase: WorkingPhase;
    activity?: ActivityItem;
    elapsedMs?: number;
}) => {
    const state = WORKING_STATES[phase];
    const symbol = state.frames[frame % state.frames.length];
    const activityLabel = activity?.summary || activity?.title || activity?.toolName;
    const detail = activityLabel ? `${phaseDisplayLabel(phase)} · ${activityLabel}` : phaseDisplayLabel(phase);
    return (
        <Box width={width} backgroundColor={THEME.panelSoftBg} paddingX={1} justifyContent="space-between">
            <Box>
                <Text color={state.color}>{symbol}</Text>
                <Text color={NEXUS_ORANGE_BRIGHT} bold> Working</Text>
                <Text color="grey">  {detail}</Text>
            </Box>
            {width >= 60 && <Text color="grey">{formatElapsed(elapsedMs)}  ·  Tab focus · Enter details</Text>}
        </Box>
    );
});

export const VoiceEqualizer = React.memo(({phase, frame, color, bars = 10}: {
    phase: string;
    frame: number;
    color?: string;
    bars?: number;
}) => {
    const symbol = WORKING_STATES.thinking.frames[Math.abs(frame) % WORKING_STATES.thinking.frames.length];
    return <Text color={color || voicePhaseColor(phase)}>{symbol}</Text>;
});
