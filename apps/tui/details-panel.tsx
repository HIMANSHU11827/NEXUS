/**
 * Nexus TUI v3.0 — Details Panels
 * Question selector, plan overview, and focused activity detail panels.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {ActivityCard} from './activity-card.js';
import {THEME, type ActivityItem, type PendingApproval, type PendingQuestion, type PlanChecklistItem} from './helpers.js';
import {NEXUS_BLUE, NEXUS_BLUE_BRIGHT, NEXUS_ORANGE_BRIGHT} from './theme.js';

export const ActivityPanelBody = React.memo(({activity, width}: {activity: ActivityItem | null; width: number}) => (
    <Box flexDirection="column" flexGrow={1}>
        {activity ? (
            <ActivityCard activity={activity as any} width={Math.max(20, width - 2)} defaultExpanded={true} showSources={true} />
        ) : (
            <Text color="grey30">Select an activity</Text>
        )}
        <Box flexGrow={1} />
    </Box>
));

export const QuestionPanelBody = React.memo(({
    question,
    selectedIndex,
    customActive,
    width
}: {
    question: PendingQuestion | null;
    selectedIndex: number;
    customActive: boolean;
    width: number;
}) => (
    <Box flexDirection="column" flexGrow={1}>
        {question ? (
            <>
                <Box flexDirection="column" marginBottom={1} backgroundColor={THEME.panelSoftBg} paddingX={1} paddingY={1}>
                    <Text color={NEXUS_BLUE_BRIGHT} bold>NEXUS NEEDS YOUR INPUT</Text>
                    <Text color="grey">Choose the best response, or write your own.</Text>
                </Box>

                <Box marginBottom={1} paddingX={1}>
                    <Text color="white" bold wrap="wrap">{question.prompt}</Text>
                </Box>

                {question.options.map((option, index) => (
                    <Box
                        key={`${question.id}-${index}`}
                        width={Math.max(12, width - 2)}
                        marginBottom={1}
                        paddingX={1}
                        backgroundColor={index === selectedIndex ? '#123044' : THEME.panelSoftBg}
                    >
                        <Text color={index === selectedIndex ? NEXUS_BLUE_BRIGHT : 'white'} bold={index === selectedIndex} wrap="wrap">
                            <Text color={index === selectedIndex ? NEXUS_BLUE_BRIGHT : 'grey'} bold>{index === selectedIndex ? '›' : ' '} {index + 1}. </Text>
                            {option}
                        </Text>
                    </Box>
                ))}

                {question.allowCustom !== false && (
                    <Box
                        width={Math.max(12, width - 2)}
                        marginBottom={1}
                        paddingX={1}
                        backgroundColor={selectedIndex === question.options.length || customActive ? '#3a2818' : THEME.panelSoftBg}
                    >
                        <Text
                            color={selectedIndex === question.options.length || customActive ? NEXUS_ORANGE_BRIGHT : 'white'}
                            bold={selectedIndex === question.options.length || customActive}
                            wrap="wrap"
                        >
                            {selectedIndex === question.options.length ? '›' : ' '} {question.options.length + 1}. {customActive ? 'Type your answer in the composer below' : 'Write a different answer'}
                        </Text>
                    </Box>
                )}

                <Box marginTop={1} paddingX={1}>
                    <Text color="grey">↑↓ move  ·  Enter choose  ·  1–9 quick select</Text>
                </Box>
            </>
        ) : (
            <Text color="grey">No pending question</Text>
        )}

        <Box flexGrow={1} />
    </Box>
));

export const ApprovalPanelBody = React.memo(({approval, width}: {approval: PendingApproval | null; width: number}) => (
    <Box flexDirection="column" flexGrow={1}>
        {approval ? (
            <>
                <Box flexDirection="column" marginBottom={1} backgroundColor={THEME.panelSoftBg} paddingX={1} paddingY={1}>
                    <Text color={NEXUS_ORANGE_BRIGHT} bold>APPROVAL REQUIRED</Text>
                    <Text color="grey">NEXUS is paused until you choose an action.</Text>
                </Box>
                <Box flexDirection="column" marginBottom={1} paddingX={1}>
                    <Text color="white" bold wrap="wrap">Approve {approval.tool}?</Text>
                    <Text color="grey" wrap="wrap">tool: {approval.tool}</Text>
                    {approval.action && <Text color="white" wrap="wrap">action: {approval.action}</Text>}
                    {approval.reason && <Text color="grey" wrap="wrap">reason: {approval.reason}</Text>}
                </Box>
                <Box width={Math.max(12, width - 2)} marginBottom={1} paddingX={1} backgroundColor="#123044">
                    <Text color={NEXUS_BLUE_BRIGHT} bold wrap="wrap">1. Allow once</Text>
                </Box>
                <Box width={Math.max(12, width - 2)} marginBottom={1} paddingX={1} backgroundColor="#3a2818">
                    <Text color={NEXUS_ORANGE_BRIGHT} bold wrap="wrap">2. Allow always for this tool</Text>
                </Box>
                <Box width={Math.max(12, width - 2)} marginBottom={1} paddingX={1} backgroundColor={THEME.panelSoftBg}>
                    <Text color="white" wrap="wrap">3. Deny</Text>
                </Box>
                <Box marginTop={1} paddingX={1}>
                    <Text color="grey">y/1 allow  ·  a/2 always  ·  n/3 or Esc deny</Text>
                </Box>
            </>
        ) : <Text color="grey">No pending approval</Text>}
        <Box flexGrow={1} />
    </Box>
));

const planStepPresentation = (status: string): {glyph: string; color: string} => {
    if (status === 'done') return {glyph: '✓', color: 'green'};
    if (status === 'failed') return {glyph: '×', color: 'red'};
    if (status === 'blocked') return {glyph: '!', color: NEXUS_ORANGE_BRIGHT};
    if (status === 'cancelled') return {glyph: '−', color: 'grey'};
    if (status === 'skipped') return {glyph: '–', color: 'grey30'};
    if (status === 'running') return {glyph: '▶', color: NEXUS_BLUE_BRIGHT};
    return {glyph: '·', color: 'grey30'};
};

export const PlanChecklistRows = React.memo(({
    items,
    maxItems = 12,
    showEvidence = false
}: {
    items: PlanChecklistItem[];
    maxItems?: number;
    showEvidence?: boolean;
}) => (
    <Box flexDirection="column">
        {items.slice(0, Math.max(1, maxItems)).map(item => {
            const presentation = planStepPresentation(item.status);
            return (
                <Box key={item.id} flexDirection="column">
                    <Box>
                        <Box width={3} flexShrink={0}>
                            <Text color={presentation.color} bold={item.status === 'running' || item.status === 'failed'}>{presentation.glyph} </Text>
                        </Box>
                        <Text color={item.status === 'done' ? 'grey' : 'white'} wrap="wrap">{item.description}</Text>
                    </Box>
                    {showEvidence && item.evidence && (
                        <Box paddingLeft={3}><Text color="grey30" wrap="wrap">evidence: {item.evidence}</Text></Box>
                    )}
                    {showEvidence && item.retryReason && (
                        <Box paddingLeft={3}><Text color={NEXUS_ORANGE_BRIGHT} wrap="wrap">retry: {item.retryReason}</Text></Box>
                    )}
                    {showEvidence && item.nextAction && (
                        <Box paddingLeft={3}><Text color="grey30" wrap="wrap">next: {item.nextAction.replace(/[_-]+/g, ' ')}</Text></Box>
                    )}
                </Box>
            );
        })}
        {items.length > maxItems && <Text color="grey30">  +{items.length - maxItems} more steps</Text>}
    </Box>
));

export const PlanPanelBody = React.memo(({
    items,
    status,
    expanded
}: {
    items: PlanChecklistItem[];
    status: string;
    expanded: boolean;
}) => (
    <Box flexDirection="column" flexGrow={1}>
        <Box justifyContent="space-between" marginBottom={1}>
            <Text color={expanded ? 'white' : 'grey'} bold>{expanded ? '▾' : '▸'} {items.length > 1 ? 'Advanced Planning' : 'Simple Planning'}</Text>
            <Text color={status === 'failed' ? 'red' : status === 'done' ? 'green' : NEXUS_BLUE}>{status}</Text>
        </Box>
        {expanded && (
            <Box marginBottom={1}><Text color="grey30">Planning process</Text></Box>
        )}
        {expanded && (items.length > 0
            ? <PlanChecklistRows items={items} showEvidence={true} />
            : <Text color="grey30">Resolving plan steps…</Text>)}
        {!expanded && <Text color="grey30">click to show planning details</Text>}
    </Box>
));
