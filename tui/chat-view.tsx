/**
 * Nexus TUI v3.0 — Chat View
 * Chat line building (markdown, activity rows, voice previews) and row renderers.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {renderTerminalMarkdown} from './terminal-markdown.js';
import {InlineActivity} from './inline-activity.js';
import {TRANSCRIPT_SURFACE_BG} from './theme.js';
import {
    CHAT_ACTIVITY_KINDS,
    activityGlyph,
    activityColor,
    formatDurationMs,
    compactActivityOutputPreview,
    activityPreviewLabel,
    cleanVisibleAssistantText,
    voicePhaseLabel,
    voicePhaseColor,
    CLAUDE_SPINNER_FRAMES,
    type ChatLine,
    type Message,
    type ActivityItem,
    type WorkingPhase
} from './helpers.js';

const wrapPlainLine = (line: string, width: number) => {
    const normalized = line.replace(/\t/g, '    ');
    if (normalized.length === 0) return [''];

    const rows: string[] = [];
    let rest = normalized;
    while (rest.length > width) {
        let cut = rest.lastIndexOf(' ', width);
        if (cut <= 0) cut = width;
        rows.push(rest.slice(0, cut).trimEnd());
        rest = rest.slice(cut).trimStart();
    }
    rows.push(rest);
    return rows;
};

const phaseThoughtText = (phase: WorkingPhase) => {
    const labels: Partial<Record<WorkingPhase, string>> = {
        querying: 'Sending your request to the selected provider.',
        streaming: 'Receiving the assistant response.',
        tool: 'Waiting for a tool result.',
        hive: 'Waiting for active subagents.',
        verifying: 'Waiting for verification results.'
    };
    return labels[phase] || 'Waiting for the next confirmed agent event.';
};

export const activityIdsFromChatLines = (lines: ChatLine[]): string[] =>
    [...new Set(lines.map(line => line.activityId).filter((id): id is string => Boolean(id)))];

export const nextActivityFocus = (
    ids: string[],
    currentId: string | null,
    backwards = false
): string | null => {
    if (ids.length === 0) return null;
    const currentIndex = currentId ? ids.indexOf(currentId) : -1;
    if (currentIndex < 0) return backwards ? ids[ids.length - 1] : ids[0];
    const delta = backwards ? -1 : 1;
    return ids[(currentIndex + delta + ids.length) % ids.length];
};

export const toggleActivityExpansion = (currentId: string | null, activityId: string): string | null =>
    currentId === activityId ? null : activityId;

export const buildThinkingRows = (
    width: number,
    phase: WorkingPhase,
    prompt: string,
    startedAt: number | null,
    frame = 0
): ChatLine[] => {
    const rows: ChatLine[] = [];
    const duration = startedAt ? formatDurationMs(Date.now() - startedAt) : '';
    const active = ['thinking', 'querying', 'streaming', 'tool'].includes(phase);
    const spinner = active ? CLAUDE_SPINNER_FRAMES[Math.abs(frame) % CLAUDE_SPINNER_FRAMES.length] : '';
    const appendWrapped = (key: string, content: string, color = 'grey', prefix = '  ', prefixColor = 'grey') => {
        const contentWidth = Math.max(1, width - prefix.length);
        let first = true;
        for (const sourceLine of content.replace(/\r/g, '').split('\n')) {
            for (const wrapped of wrapPlainLine(sourceLine, contentWidth)) {
                rows.push({
                    key: `thinking-${key}-${rows.length}`,
                    text: wrapped,
                    color,
                    prefix: first ? prefix : '  ',
                    prefixColor,
                    reservePrefix: true
                });
                first = false;
            }
        }
    };

    rows.push({
        key: 'thinking-detail-header',
        text: `${spinner ? `${spinner} ` : ''}Run status:${duration ? ` ${duration}` : ''}`,
        color: 'yellowBright',
        prefix: '+ ',
        prefixColor: 'yellowBright',
        reservePrefix: true,
        bold: true
    });
    rows.push({key: 'thinking-detail-gap-1', text: '', color: 'grey'});
    appendWrapped('summary', phaseThoughtText(phase), 'grey');

    return rows.slice(0, 12);
};

export const HistoryItem = ({
    msg,
    activity,
    width,
    index
}: {
    msg: Message;
    activity?: ActivityItem;
    width: number;
    index: number;
}) => {
    if (msg.role === 'assistant' && msg.content.trim().length === 0) {
        return null;
    }

    if (msg.role === 'activity' && activity) {
        return (
            <Box marginTop={index > 0 ? 1 : 0} marginBottom={1} width={width}>
                <Text color={activity.logoColor || activityColor(activity.kind)}>{activity.logo || activityGlyph(activity.kind)} </Text>
                <Text color="grey">{activity.title}</Text>
                <Text color="grey30">  › </Text>
                <Text color="grey30">/open {activity.number}</Text>
            </Box>
        );
    }

    const prefix = msg.role === 'user' ? '> ' : msg.role === 'command' ? '◆ ' : msg.role === 'system' ? '! ' : '';
    const prefixColor = msg.role === 'user' ? 'blue' : msg.role === 'command' ? 'cyan' : msg.role === 'system' ? 'red' : 'magenta';
    const contentWidth = Math.max(1, width - (prefix ? 2 : 0));
    const topGap = msg.role === 'user' && index > 0 ? 1 : 0;
    const bottomGap = msg.role === 'assistant' || msg.role === 'command' || msg.role === 'system' ? 1 : 0;

    return (
        <Box marginTop={topGap} marginBottom={bottomGap} width={width}>
            {prefix && (
                <Box width={2} flexShrink={0}>
                    <Text bold color={prefixColor}>{prefix}</Text>
                </Box>
            )}
            <Box width={contentWidth}>
                <Text wrap="wrap" color={msg.role === 'system' ? "red" : msg.role === 'command' ? "grey" : "white"}>
                    {msg.content}
                </Text>
            </Box>
        </Box>
    );
};

export const activityDetailBoxRows = (activity: ActivityItem, width: number, showSources: boolean): string[] => {
    const innerWidth = Math.max(10, width - 4);
    const rows: string[] = [];
    const push = (value = '') => {
        for (const line of wrapPlainLine(value, innerWidth)) {
            rows.push(line);
        }
    };
    const duration = formatDurationMs(activity.durationMs);
    const header = `${activity.toolName || activity.kind}${duration ? ` · ${duration}` : ''}`;
    // Expanded details use the same filled transcript surface as user and
    // Nexus messages. Blank edge rows provide breathing room without a box.
    push('');
    push(header);
    const summary = activity.summary && activity.summary !== activity.toolName ? activity.summary : '';
    if (summary) push(summary);
    const policyParts = [
        activity.intent ? `intent: ${activity.intent}` : '',
        activity.oneTimeUse ? 'one-time' : '',
        activity.maxPerTask ? `max/task: ${activity.maxPerTask}` : '',
        activity.parallel !== undefined ? `parallel: ${activity.parallel ? 'yes' : 'no'}` : '',
        activity.maxParallel ? `max: ${activity.maxParallel}` : '',
        activity.cooldownMs ? `cooldown: ${formatDurationMs(activity.cooldownMs)}` : ''
    ].filter(Boolean);
    if (policyParts.length > 0) {
        push('');
        push(policyParts.join(' · '));
    }
    const shouldShowInput = activity.showInput !== false;
    if (shouldShowInput && activity.command && activity.command !== summary) {
        push('');
        push(`command: ${activity.command}`);
    }
    if (shouldShowInput && activity.operation) {
        push('');
        push(`operation: ${activity.operation}`);
    }
    if (shouldShowInput && activity.files?.length) {
        push('');
        push(`files: ${activity.files.join(', ')}`);
    }
    const detail = compactActivityOutputPreview(activity);
    if (detail) {
        push('');
        push(activityPreviewLabel(activity));
        for (const line of detail.split('\n')) push(line);
    }
    const shouldShowSources = showSources || activity.showSources === true;
    if (shouldShowSources && activity.sources?.length) {
        push('');
        push('sources');
        for (const source of activity.sources.slice(0, 5)) push(source);
    }
    push('');
    return rows;
};

export const buildChatLines = (
    history: Message[],
    activityItems: ActivityItem[],
    width: number,
    focusedActivityId: string | null,
    expandedActivityId: string | null,
    showActivitySources: boolean
): ChatLine[] => {
    const rows: ChatLine[] = [];
    const activityById = new Map(activityItems.map(activity => [activity.id, activity]));
    const appendGap = (key: string) => {
        if (rows.length > 0 && rows[rows.length - 1].text !== '') {
            rows.push({key, text: '', color: 'grey'});
        }
    };

    const appendWrapped = (
        key: string,
        content: string,
        color: string,
        prefix = '',
        prefixColor = 'grey',
        repeatPrefix = false
    ) => {
        const reservePrefix = prefix.length > 0;
        const contentWidth = Math.max(1, width - (reservePrefix ? prefix.length : 0));
        const sourceLines = content.replace(/\r/g, '').split('\n');
        let first = true;

        for (const sourceLine of sourceLines) {
            for (const wrapped of wrapPlainLine(sourceLine, contentWidth)) {
                rows.push({
                    key: `${key}-${rows.length}`,
                    text: wrapped,
                    color,
                    prefix: first || repeatPrefix ? prefix : undefined,
                    prefixColor,
                    reservePrefix
                });
                first = false;
            }
        }
    };

    history.forEach((msg, index) => {
        if (msg.role === 'assistant' && msg.content.trim().length === 0) return;

        if (msg.role === 'user') {
            appendGap(`before-user-${index}`);
            const start = rows.length;
            appendWrapped(`user-${index}`, msg.content, 'white', '› ', 'grey');
            for (let rowIndex = start; rowIndex < rows.length; rowIndex += 1) {
                rows[rowIndex].backgroundColor = TRANSCRIPT_SURFACE_BG;
            }
            appendGap(`after-user-${index}`);
            return;
        }

        if (msg.role === 'activity') {
            const activity = msg.activityId ? activityById.get(msg.activityId) : undefined;
            if (!activity || !CHAT_ACTIVITY_KINDS.has(activity.kind)) return;
            // v3: push ActivityCard via ChatLine.activity
            rows.push({
                key: `activity-${index}`,
                text: '',
                color: 'grey',
                activityId: activity.id,
                activity,
                focused: focusedActivityId === activity.id,
                expanded: expandedActivityId === activity.id
            });
            if (activity.kind === 'plan' && activity.detail && expandedActivityId === activity.id) {
                const planDetails = ['', ...String(activity.detail).split('\n').slice(0, 6), ''];
                for (const [detailIndex, detail] of planDetails.entries()) {
                    rows.push({
                        key: `activity-plan-${index}-${detailIndex}`,
                        text: detail,
                        color: 'grey',
                        prefix: '  ',
                        prefixColor: 'grey',
                        reservePrefix: true,
                        activityId: activity.id,
                        backgroundColor: TRANSCRIPT_SURFACE_BG
                    });
                }
            }
            if (expandedActivityId === activity.id && activity.kind !== 'plan') {
                for (const [detailIndex, line] of activityDetailBoxRows(activity, width, showActivitySources).entries()) {
                    rows.push({
                        key: `activity-detail-${index}-${detailIndex}`,
                        text: line,
                        color: activity.error ? 'red' : 'grey30',
                        prefix: '  ',
                        prefixColor: activity.logoColor || 'grey30',
                        reservePrefix: true,
                        activityId: activity.id,
                        backgroundColor: TRANSCRIPT_SURFACE_BG
                    });
                }
            }
            return;
        }

        if (msg.role === 'command') {
            appendWrapped(`command-${index}`, msg.content, 'grey', '◆ ', 'cyan');
            appendGap(`after-command-${index}`);
            return;
        }

        if (msg.role === 'system') {
            appendWrapped(`system-${index}`, msg.content, 'red', '! ', 'red');
            appendGap(`after-system-${index}`);
            return;
        }

        appendGap(`before-assistant-${index}`);
        const assistantStart = rows.length;
        appendWrapped(
            `assistant-${index}`,
            renderTerminalMarkdown(
                cleanVisibleAssistantText(msg.content),
                Math.max(20, width - 'Nexus > '.length)
            ),
            'white',
            'Nexus > ',
            'magentaBright'
        );
        // Use the same full-width message surface for both sides of the
        // conversation. The role prefix remains inside the panel; live tool
        // rows deliberately keep their compact activity treatment.
        for (let rowIndex = assistantStart; rowIndex < rows.length; rowIndex += 1) {
            rows[rowIndex].backgroundColor = TRANSCRIPT_SURFACE_BG;
        }
        appendGap(`after-assistant-${index}`);
    });

    return rows;
};

export const appendVoicePreviewLines = (
    rows: ChatLine[],
    width: number,
    voiceMode: 'off' | 'auto' | 'manual' | 'text',
    voicePhase: string,
    voiceTranscriptPreview: string,
    voiceReplyPreview: string,
    history: Message[]
) => {
    if (voiceMode === 'off') return rows;

    const latestUser = [...history].reverse().find(msg => msg.role === 'user')?.content.trim() || '';
    const latestAssistant = [...history].reverse().find(msg => msg.role === 'assistant')?.content.trim() || '';
    const transcript = String(voiceTranscriptPreview || '').trim();
    const reply = String(voiceReplyPreview || '').trim();
    const normalizedLatestAssistant = cleanVisibleAssistantText(latestAssistant);

    const appendWrapped = (
        key: string,
        content: string,
        color: string,
        prefix = '',
        prefixColor = 'grey',
        repeatPrefix = false
    ) => {
        const reservePrefix = prefix.length > 0;
        const contentWidth = Math.max(1, width - (reservePrefix ? prefix.length : 0));
        const sourceLines = content.replace(/\r/g, '').split('\n');
        let first = true;

        for (const sourceLine of sourceLines) {
            for (const wrapped of wrapPlainLine(sourceLine, contentWidth)) {
                rows.push({
                    key: `${key}-${rows.length}`,
                    text: wrapped,
                    color,
                    prefix: first || repeatPrefix ? prefix : undefined,
                    prefixColor,
                    reservePrefix
                });
                first = false;
            }
        }
    };

    if (rows.length > 0 && rows[rows.length - 1].text !== '') {
        rows.push({key: `voice-gap-${rows.length}`, text: '', color: 'grey'});
    }

    if (transcript && transcript !== latestUser) {
        appendWrapped(`voice-heard-${rows.length}`, transcript, 'green', '> ', 'blue');
    }

    if (reply && reply !== normalizedLatestAssistant) {
        appendWrapped(`voice-reply-${rows.length}`, reply, 'yellow');
    }

    const statusText = `🎙 ${voiceMode} · ${voicePhaseLabel(voicePhase)}`;
    appendWrapped(`voice-status-${rows.length}`, statusText, voicePhaseColor(voicePhase));

    return rows;
};

export const ChatLineView = React.memo(({line, width, frame}: {line: ChatLine; width: number; frame: number}) => {
    const prefixWidth = line.reservePrefix ? Math.max(1, line.prefix?.length || 2) : 0;
    const contentWidth = Math.max(1, width - prefixWidth);

    // v3: opencode-style inline tool/activity row for activity chat lines
    if (line.activity) {
        const act = line.activity as any;
        return (
            <Box width={width} marginBottom={0}>
                <InlineActivity activity={act} width={width} frame={frame} focused={line.focused} expanded={line.expanded} />
            </Box>
        );
    }

    return (
        <Box width={width} backgroundColor={line.backgroundColor}>
            {line.reservePrefix && (
                <Box width={prefixWidth} flexShrink={0}>
                    <Text bold color={line.prefixColor}>{line.prefix || '  '}</Text>
                </Box>
            )}
            <Box width={contentWidth}>
                <Text color={line.color} bold={line.bold}>{line.text || ' '}</Text>
            </Box>
        </Box>
    );
});
