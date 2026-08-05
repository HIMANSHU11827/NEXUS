/**
 * Nexus TUI v3.0 — Details Panels
 * Question selector, plan overview, and focused activity detail panels.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {ActivityCard} from './activity-card.js';
import type {ActivityItem, PendingQuestion} from './helpers.js';

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
    customActive
}: {
    question: PendingQuestion | null;
    selectedIndex: number;
    customActive: boolean;
}) => (
    <Box flexDirection="column" flexGrow={1}>
        <Box marginBottom={1}>
            <Text color="white" bold>Question</Text>
        </Box>

        {question ? (
            <>
                <Box marginBottom={1}>
                    <Text color="white" wrap="wrap">{question.prompt}</Text>
                </Box>

                {question.options.map((option, index) => (
                    <Box key={`${question.id}-${index}`} marginTop={1}>
                        <Box width={3}>
                            <Text color={index === selectedIndex ? 'cyanBright' : 'cyan'} bold={index === selectedIndex}>
                                {index === selectedIndex ? '›' : ' '}{index + 1}.
                            </Text>
                        </Box>
                        <Text
                            color={index === selectedIndex ? 'cyanBright' : 'white'}
                            bold={index === selectedIndex}
                            wrap="wrap"
                        >
                            {option}
                        </Text>
                    </Box>
                ))}

                {question.allowCustom !== false && (
                    <Box marginTop={1}>
                        <Box width={3}>
                            <Text color="magenta">{question.options.length + 1}.</Text>
                        </Box>
                        <Text color={customActive ? 'magentaBright' : 'grey'} bold={customActive}>type your own answer in chat box{customActive ? ' (active)' : ''}</Text>
                    </Box>
                )}

                <Box marginTop={1}>
                    <Text color="grey30">↑/↓ or wheel to select · Enter/number to choose</Text>
                </Box>
            </>
        ) : (
            <Text color="grey30">No pending question</Text>
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