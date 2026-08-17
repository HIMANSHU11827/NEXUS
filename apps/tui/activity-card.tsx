/**
 * Nexus TUI v3.0 — Activity Card Component
 * Collapsible, color-coded activity cards replacing ASCII boxes.
 */
import React, {useState} from 'react';
import {Box, Text} from 'ink';
import type {ActivityItem} from './types.js';
import {activityColor, activityGlyph, statusColor, statusGlyph, getTheme} from './theme.js';

interface ActivityCardProps {
    activity: ActivityItem;
    width: number;
    index?: number;
    defaultExpanded?: boolean;
    showSources?: boolean;
}

function truncateOutput(output: string, maxLines = 10, maxChars = 500): string {
    const lines = output.split('\n');
    if (lines.length <= maxLines && output.length <= maxChars) return output.trim();
    const sliced = lines.slice(0, maxLines).join('\n');
    const truncated = sliced.length > maxChars ? sliced.slice(0, maxChars) : sliced;
    return `${truncated}\n... (${lines.length - maxLines} more lines)`;
}

function sanitizeTerminalText(value: string): string {
    // Tool output can contain ANSI/control sequences that corrupt Ink's layout.
    return value.replace(/[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F]/g, '');
}

export const ActivityCard: React.FC<ActivityCardProps> = ({
    activity, width, index = 0, defaultExpanded = false, showSources = false,
}) => {
    const [expanded, setExpanded] = useState(defaultExpanded);
    const theme = getTheme();
    const kind = activity.kind || 'tool';
    const glyph = activity.logo || activityGlyph(kind);
    const color = activity.logoColor || activityColor(kind);
    const statColor = statusColor(activity.status);
    const statGlyph = statusGlyph(activity.status);
    const duration = activity.durationMs
        ? activity.durationMs >= 1000
            ? `${(activity.durationMs / 1000).toFixed(1)}s`
            : `${activity.durationMs}ms`
        : '';
    const output = sanitizeTerminalText(activity.output || activity.error || '');
    const hasOutput = output.length > 0;
    const boxWidth = Math.max(10, Math.min(Math.max(10, width - 4), 80));

    return (
        <Box flexDirection="column" marginTop={index > 0 ? 1 : 0} width={width}>
            {/* Header row */}
            <Box width={width}>
                <Text color={color} bold>{glyph} </Text>
                <Text color={statColor} bold>{statGlyph} </Text>
                <Text color={color}>{activity.toolName || kind}</Text>
                {duration ? <Text color={theme.textDim}> · {duration}</Text> : null}
                {activity.number ? <Text color={theme.textMuted}>  #{activity.number}</Text> : null}
            </Box>
            {/* Summary */}
            {activity.summary && activity.summary !== activity.toolName && (
                <Box width={width} paddingLeft={2}>
                    <Text color={theme.textDim} wrap="wrap">{activity.summary}</Text>
                </Box>
            )}
            {/* Command */}
            {activity.command && (
                <Box width={width} paddingLeft={2}>
                    <Text color={theme.textMuted}>$ {activity.command}</Text>
                </Box>
            )}
            {/* Files */}
            {activity.files?.length ? (
                <Box width={width} paddingLeft={2}>
                    <Text color={theme.textMuted}>files: {activity.files.slice(0,5).join(', ')}</Text>
                </Box>
            ) : null}
            {/* Expandable output */}
            {hasOutput && (
                <Box flexDirection="column" marginTop={0}>
                    <Box paddingLeft={0}>
                        <Text color={theme.secondary}>{expanded ? '▼' : '▶'} output ({output.split('\n').length} lines)</Text>
                    </Box>
                    {expanded && (
                        <Box flexDirection="column" paddingLeft={2} borderStyle="single"
                            borderColor={theme.borderSoft} paddingX={1} marginTop={0} width={boxWidth}>
                            {truncateOutput(output, 12, 800).split('\n').map((line, i) => (
                                <Text key={i} color={activity.status === 'error' ? theme.error : theme.textDim}>
                                    {line || ' '}
                                </Text>
                            ))}
                        </Box>
                    )}
                </Box>
            )}
            {/* Sources */}
            {showSources && activity.sources?.length ? (
                <Box flexDirection="column" paddingLeft={2} marginTop={0}>
                    <Text color={theme.textMuted}>sources:</Text>
                    {activity.sources.slice(0, 5).map((src, i) => (
                        <Text key={i} color={theme.textDim}>  • {src}</Text>
                    ))}
                </Box>
            ) : null}
            {/* Policy */}
            {activity.intent && (
                <Box paddingLeft={2}>
                    <Text color={theme.textMuted}>
                        intent: {activity.intent}
                        {activity.oneTimeUse ? ' · one-time' : ''}
                        {activity.maxPerTask ? ` · max/task: ${activity.maxPerTask}` : ''}
                    </Text>
                </Box>
            )}
        </Box>
    );
};
