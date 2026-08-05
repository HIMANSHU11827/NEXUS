/**
 * Nexus TUI v3.0 — Banner & Working Status
 * NEXUS wordmark banner, phase-aware working indicator, and voice equalizer.
 */
import React from 'react';
import {Box, Text} from 'ink';
import Gradient from 'ink-gradient';
import {voiceBarsForFrame, voicePhaseColor, WORKING_STATES, THEME, type WorkingPhase} from './helpers.js';

const NEXUS_WORDMARK = [
    '███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗',
    '████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝',
    '██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗',
    '██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║',
    '██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║',
    '╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝'
].join('\n');

export const NexusBanner = React.memo(({width}: {width: number}) => {
    if (width < 72) {
        return (
            <Box height={2} paddingX={1}>
                <Text bold color="cyanBright">NEXUS</Text>
            </Box>
        );
    }

    return (
        <Box height={7} paddingX={1} overflow="hidden">
            <Gradient name="rainbow">
                <Text>{NEXUS_WORDMARK}</Text>
            </Gradient>
        </Box>
    );
});

export const WorkingStatus = React.memo(({frame, width, phase}: {frame: number; width: number; phase: WorkingPhase}) => {
    const state = WORKING_STATES[phase];
    const symbol = state.frames[frame % state.frames.length];
    const label = state.label;
    const action = state.action ? ` ${state.action}` : '';
    const status = state.status ? ` ${state.status}` : '';

    return (
        <Box width={width} backgroundColor={THEME.panelSoftBg} paddingX={1}>
            <Text color={state.color}>{symbol}</Text>
            <Text color="grey">{` ${label}`}</Text>
            <Text color={state.color}>{action}</Text>
            <Text color="grey">{status}</Text>
        </Box>
    );
});

export const VoiceEqualizer = React.memo(({
    phase,
    frame,
    color,
    bars = 10
}: {
    phase: string;
    frame: number;
    color?: string;
    bars?: number;
}) => {
    const heights = voiceBarsForFrame(phase, frame, bars);
    return (
        <Box>
            {heights.map((height, index) => (
                <Text key={`voice-bar-${index}`} color={color || voicePhaseColor(phase)}>
                    {'▁▂▃▄▅▆▇█'[Math.max(0, Math.min(7, height - 1))]}{index < heights.length - 1 ? ' ' : ''}
                </Text>
            ))}
        </Box>
    );
});