/**
 * Nexus TUI v3.0 — Hive Agent Panel
 * Expandable rows showing agent status, activity, tools, files, errors, retries.
 */
import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';
import type {AgentInfo, TaskItem} from './types.js';
import {statusColor, statusGlyph, taskStatusGlyph, getTheme} from './theme.js';

interface HivePanelBodyProps {
    agents: AgentInfo[];
    selectedAgentId: string | null;
    tasks: TaskItem[];
    width?: number;
}

function formatMs(ms?: number): string {
    if (!ms) return '';
    if (ms >= 60000) return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${ms}ms`;
}

const AgentRow: React.FC<{agent: AgentInfo; isSelected: boolean; width: number}> = ({agent, isSelected, width}) => {
    const [expanded, setExpanded] = useState(isSelected);
    useEffect(() => {
        if (isSelected) setExpanded(true);
    }, [isSelected]);
    const theme = getTheme();
    const color = statusColor(agent.status);
    const glyph = statusGlyph(agent.status);

    return (
        <Box flexDirection="column" width={width}>
            <Box width={width} justifyContent="space-between">
                <Box>
                    <Text color={color}>{glyph} </Text>
                    <Text color={color} bold>{agent.name || agent.persona || agent.agentId || 'Agent'}</Text>
                    {agent.activity ? <Text color={theme.textDim}>  {agent.activity}</Text> : null}
                </Box>
                <Text color={theme.textMuted}>{formatMs(agent.durationMs)}</Text>
            </Box>
            {expanded && (
                <Box flexDirection="column" paddingLeft={2} marginTop={0} borderStyle="single"
                    borderColor={theme.borderSoft} paddingX={1}>
                    {agent.task && <Box><Text color={theme.textDim}>task: </Text><Text color={theme.text} wrap="wrap">{agent.task}</Text></Box>}
                    {agent.persona && <Box><Text color={theme.textDim}>persona: </Text><Text color={theme.text}>{agent.persona}</Text></Box>}
                    {agent.toolsUsed !== undefined && <Box><Text color={theme.textDim}>tools: </Text><Text color={theme.text}>{agent.toolsUsed}</Text></Box>}
                    {agent.messages !== undefined && <Box><Text color={theme.textDim}>messages: </Text><Text color={theme.text}>{agent.messages}</Text></Box>}
                    {agent.filesChanged?.length ? (
                        <Box flexDirection="column">
                            <Text color={theme.textDim}>files:</Text>
                            {agent.filesChanged.map((f, i) => <Text key={i} color={theme.success}>  + {f}</Text>)}
                        </Box>
                    ) : null}
                    {agent.errors?.length ? (
                        <Box flexDirection="column">
                            <Text color={theme.error}>errors:</Text>
                            {agent.errors.map((e, i) => <Text key={i} color={theme.error}>  ! {e}</Text>)}
                        </Box>
                    ) : null}
                    {agent.retryCount !== undefined && agent.retryCount > 0 && (
                        <Box><Text color={theme.warning}>retries: {agent.retryCount}</Text></Box>
                    )}
                    {agent.finalResult && (
                        <Box flexDirection="column">
                            <Text color={theme.success} bold>result:</Text>
                            <Text color={theme.text} wrap="wrap">{agent.finalResult}</Text>
                        </Box>
                    )}
                </Box>
            )}
        </Box>
    );
};

export const HivePanelBody: React.FC<HivePanelBodyProps> = ({agents, selectedAgentId, tasks, width = 40}) => {
    if (agents.length === 0) return null;

    const theme = getTheme();
    const activeCount = agents.filter(a =>
        ['active','running','working','busy','spawned','in_progress'].includes(String(a.status).toLowerCase())
    ).length;
    const completedCount = agents.filter(a =>
        ['done','completed','success','finished'].includes(String(a.status).toLowerCase())
    ).length;
    const failedCount = agents.filter(a =>
        ['error','failed','cancelled'].includes(String(a.status).toLowerCase())
    ).length;

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box justifyContent="space-between" marginBottom={1}>
                <Text color="white" bold>🐝 Hive Agents</Text>
                <Box>
                    {activeCount > 0 && <Text color={theme.statusRunning}> {activeCount} active</Text>}
                    {completedCount > 0 && <Text color={theme.statusDone}> {completedCount} done</Text>}
                    {failedCount > 0 && <Text color={theme.statusError}> {failedCount} failed</Text>}
                </Box>
            </Box>
            {agents.length === 0 ? (
                <Text color={theme.textMuted}>No agents active</Text>
            ) : (
                agents.slice(0, 15).map((agent, i) => (
                    <AgentRow key={agent.id || i} agent={agent} isSelected={agent.id === selectedAgentId} width={Math.max(20, width - 2)} />
                ))
            )}
            {tasks.length > 0 && (
                <Box flexDirection="column" marginTop={1}>
                    <Text color="white" bold>📋 Tasks</Text>
                    {tasks.slice(0, 6).map(task => (
                        <Box key={task.id} marginTop={0}>
                            <Box width={2} flexShrink={0}>
                                <Text color={statusColor(task.status)}>{taskStatusGlyph(task.status)}</Text>
                            </Box>
                            <Text color={theme.textDim} wrap="wrap">
                                {task.subject.length > 60 ? task.subject.slice(0, 57) + '...' : task.subject}
                            </Text>
                        </Box>
                    ))}
                </Box>
            )}
        </Box>
    );
};
