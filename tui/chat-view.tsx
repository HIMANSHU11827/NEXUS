/**
 * Nexus TUI v3.0 — Chat View
 * Chat line building (markdown, activity rows, voice previews) and row renderers.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {renderTerminalMarkdown} from './terminal-markdown.js';
import {InlineActivity} from './inline-activity.js';
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

const phaseThoughtText = (phase: WorkingPhase, prompt: string) => {
    const normalized = prompt.toLowerCase();
    if (normalized.includes('news') || normalized.includes('latest') || normalized.includes('today') || normalized.includes('current')) {
        return 'Need verify this with current information before answering. I am preparing the right search/query path instead of guessing.';
    }
    if (normalized.includes('code') || normalized.includes('build') || normalized.includes('create') || normalized.includes('game') || normalized.includes('fix')) {
        return 'Need turn this request into a concrete change. I am identifying the likely files, tools, and checks before editing.';
    }
    if (phase === 'querying' || phase === 'streaming') {
        return 'Reading the request and waiting for the next visible model or tool event.';
    }
    return 'Working out the next visible step from the current request.';
};

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
    const spinner = active ? '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'[Math.abs(frame) % 10] : '';
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
        text: `${spinner ? `${spinner} ` : ''}Thought:${duration ? ` ${duration}` : ''}`,
        color: 'yellowBright',
        prefix: '+ ',
        prefixColor: 'yellowBright',
        reservePrefix: true,
        bold: true
    });
    rows.push({key: 'thinking-detail-gap-1', text: '', color: 'grey'});
    appendWrapped('summary', phaseThoughtText(phase, prompt), 'grey');

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
    const boxWidth = Math.max(24, Math.min(width, 74));
    const innerWidth = Math.max(10, boxWidth - 4);
    const rows: string[] = [];
    const push = (value = '') => {
        for (const line of wrapPlainLine(value, innerWidth)) {
            rows.push(`│ ${line.padEnd(innerWidth, ' ')} │`);
        }
    };
    const duration = formatDurationMs(activity.durationMs);
    const header = `${activity.logo || activityGlyph(activity.kind)} ${activity.toolName || activity.kind} · ${activity.status}${duration ? ` · ${duration}` : ''}`;
    rows.push(`┌${'─'.repeat(boxWidth - 2)}┐`);
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
    rows.push(`└${'─'.repeat(boxWidth - 2)}┘`);
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
    let previousActivitySignature = '';
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
            previousActivitySignature = '';
            appendGap(`before-user-${index}`);
            appendWrapped(`user-${index}`, msg.content, 'white', 'You > ', 'blueBright');
            return;
        }

        if (msg.role === 'activity') {
            const activity = msg.activityId
                ? activityItems.find(item => item.id === msg.activityId)
                : undefined;
            if (!activity || !CHAT_ACTIVITY_KINDS.has(activity.kind)) return;
            const activitySignature = `${activity.toolName || activity.kind} ${activity.summary || activity.title}`;
            if (activitySignature === previousActivitySignature) return;
            previousActivitySignature = activitySignature;
            // v3: push ActivityCard via ChatLine.activity
            rows.push({
                key: `activity-${index}`,
                text: '',
                color: 'grey',
                activityId: activity.id,
                activity
            });
            if (expandedActivityId === activity.id) {
                for (const [detailIndex, line] of activityDetailBoxRows(activity, width, showActivitySources).entries()) {
                    rows.push({
                        key: `activity-detail-${index}-${detailIndex}`,
                        text: line,
                        color: activity.error ? 'red' : 'grey30',
                        prefix: '  ',
                        prefixColor: activity.logoColor || 'grey30',
                        reservePrefix: true,
                        activityId: activity.id
                    });
                }
            }
            return;
        }

        if (msg.role === 'command') {
            previousActivitySignature = '';
            appendWrapped(`command-${index}`, msg.content, 'grey', '◆ ', 'cyan');
            appendGap(`after-command-${index}`);
            return;
        }

        if (msg.role === 'system') {
            previousActivitySignature = '';
            appendWrapped(`system-${index}`, msg.content, 'red', '! ', 'red');
            appendGap(`after-system-${index}`);
            return;
        }

        previousActivitySignature = '';
        appendGap(`before-assistant-${index}`);
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
                <InlineActivity activity={act} width={width} frame={frame} />
            </Box>
        );
    }

    return (
        <Box width={width}>
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