/**
 * Nexus TUI v3.0 — Details Panels
 * Question selector, plan overview, and focused activity detail panels.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {ActivityCard} from './activity-card.js';
import {THEME, type ActivityItem, type PendingQuestion} from './helpers.js';

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
                    <Text color="cyanBright" bold>NEXUS NEEDS YOUR INPUT</Text>
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
                        backgroundColor={index === selectedIndex ? '#12313a' : THEME.panelSoftBg}
                    >
                        <Text color={index === selectedIndex ? 'cyanBright' : 'white'} bold={index === selectedIndex} wrap="wrap">
                            <Text color={index === selectedIndex ? 'cyanBright' : 'grey'} bold>{index === selectedIndex ? '›' : ' '} {index + 1}. </Text>
                            {option}
                        </Text>
                    </Box>
                ))}

                {question.allowCustom !== false && (
                    <Box
                        width={Math.max(12, width - 2)}
                        marginBottom={1}
                        paddingX={1}
                        backgroundColor={selectedIndex === question.options.length || customActive ? '#321f3d' : THEME.panelSoftBg}
                    >
                        <Text
                            color={selectedIndex === question.options.length || customActive ? 'magentaBright' : 'white'}
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

export const PlanPanelBody = React.memo(({
    items,
    status,
    expanded
}: {
    items: string[];
    status: string;
    expanded: boolean;
}) => (
    <Box flexDirection="column" flexGrow={1}>
        <Box justifyContent="space-between" marginBottom={1}>
            <Text color={expanded ? 'white' : 'grey'} bold>{expanded ? '▾' : '▸'} {items.length > 1 ? 'Advanced Planning' : 'Simple Planning'}</Text>
            <Text color={status === 'failed' ? 'red' : status === 'done' ? 'green' : 'cyan'}>{status}</Text>
        </Box>
        {expanded && (
            <Box marginBottom={1}><Text color="grey30">Planning process</Text></Box>
        )}
        {expanded && (items.length > 0 ? items.map((item, index) => (
            <Box key={`${index}-${item}`} marginTop={index === 0 ? 0 : 1}>
                <Box width={3}><Text color={status === 'done' ? 'green' : 'cyan'}>{status === 'done' ? '✓' : index + 1}.</Text></Box>
                <Text color="white" wrap="wrap">{item}</Text>
            </Box>
        )) : <Text color="grey30">Resolving plan steps…</Text>)}
        {!expanded && <Text color="grey30">click to show planning details</Text>}
    </Box>
));
