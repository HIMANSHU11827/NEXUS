/**
 * Nexus TUI v3.0 — Task List Panel
 * Compact one-line task rows with state glyph, subject, live status, agent,
 * and elapsed time, plus the workspace body that stacks tasks and hive agents.
 * All fields come from real backend state; nothing is fabricated.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {HivePanelBody} from './hive-panel.js';
import {
    taskStateGlyph,
    taskStateLabel,
    taskElapsedLabel,
    compactTaskSubject,
    type TaskItem,
    type AgentInfo
} from './helpers.js';
import {getTheme} from './theme.js';

interface TaskRowProps {
    task: TaskItem;
    width: number;
    selected?: boolean;
}

const TaskRow = React.memo(({task, width, selected}: TaskRowProps) => {
    const theme = getTheme();
    const glyph = taskStateGlyph(task.status);
    const label = taskStateLabel(task.status);
    const elapsed = taskElapsedLabel(task.startedAt);
    const lineColor = selected ? theme.text : theme.textDim;
    const glyphColor =
        glyph === '✓' ? theme.statusDone
        : glyph === '✗' || glyph === '⛔' ? theme.statusError
        : glyph === '▶' ? theme.statusRunning
        : glyph === '⏸' ? theme.warning
        : theme.statusPending;

    const subject = compactTaskSubject(task.subject, Math.max(12, width - 4));
    const meta = [
        label && glyph !== '·' ? label : '',
        task.agent ? task.agent : '',
        elapsed ? elapsed : ''
    ].filter(Boolean).join(' · ');

    return (
        <Box key={task.id} marginTop={0} width={width}>
            <Box width={2} flexShrink={0}>
                <Text color={glyphColor} bold>{glyph}</Text>
            </Box>
            <Box flexDirection="column" flexGrow={1}>
                <Text color={selected ? theme.text : theme.textDim} wrap="wrap">{subject}</Text>
                {meta ? (
                    <Text color={theme.textMuted}>{meta}</Text>
                ) : null}
            </Box>
        </Box>
    );
});

/** Compact task list panel. Each task renders as one compact block. */
export const TodoPanelBody = React.memo(({tasks, width, selectedTaskId}: {
    tasks: TaskItem[];
    width: number;
    selectedTaskId?: string | null;
}) => {
    if (tasks.length === 0) {
        return <Box flexGrow={1} />;
    }

    return (
        <Box flexDirection="column" flexGrow={1}>
            <Box marginBottom={1}>
                <Text color="white" bold>Tasks</Text>
                <Text color="grey30">  {tasks.length}</Text>
            </Box>
            <Box flexDirection="column">
                {tasks.slice(0, 12).map(task => (
                    <TaskRow key={task.id} task={task} width={width} selected={selectedTaskId === task.id} />
                ))}
            </Box>
            <Box flexGrow={1} />
        </Box>
    );
});

export const WorkspacePanelBody = React.memo(({tasks, agents, selectedAgentId, width}: {tasks: TaskItem[]; agents?: AgentInfo[]; selectedAgentId?: string | null; width: number}) => {
    const liveAgents = agents || [];
    const hasTasks = tasks.length > 0;
    const hasAgents = liveAgents.length > 0;

    return (
        <Box flexDirection="column" flexGrow={1}>
            {hasAgents && (
                // The workspace body owns the compact task list; pass an empty
                // task array so the hive section does not duplicate it.
                <HivePanelBody agents={liveAgents} selectedAgentId={selectedAgentId || null} tasks={[]} width={width} />
            )}
            {hasTasks && <TodoPanelBody tasks={tasks} width={width} />}
        </Box>
    );
});