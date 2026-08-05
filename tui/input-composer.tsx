/**
 * Nexus TUI v3.0 — Input Composer
 * Single-line input with keyboard hints and command palette trigger.
 */
import React from 'react';
import {Box, Text} from 'ink';
import TextInput from 'ink-text-input';
import {getTheme} from './theme.js';

interface InputComposerProps {
    value: string;
    onChange: (value: string) => void;
    onSubmit: (value: string) => void;
    placeholder?: string;
    isBusy?: boolean;
    showHints?: boolean;
}

export const InputComposer: React.FC<InputComposerProps> = ({
    value, onChange, onSubmit, placeholder, isBusy, showHints = true,
}) => {
    const theme = getTheme();
    const actualPlaceholder = placeholder || 'Type a message (/ for commands)...';

    return (
        <Box flexDirection="column">
            {/* Hints row */}
            {showHints && (
                <Box paddingX={1}>
                    {isBusy ? (
                        <Text color={theme.warning}>Esc to cancel  ·  agent is working...</Text>
                    ) : (
                        <Box>
                            <Text color={theme.textMuted}>Enter send</Text>
                            <Text color={theme.textDim}>  ·  </Text>
                            <Text color={theme.textMuted}>/ commands</Text>
                            <Text color={theme.textDim}>  ·  </Text>
                            <Text color={theme.textMuted}>Ctrl+K palette</Text>
                        </Box>
                    )}
                </Box>
            )}

            {/* Input row */}
            <Box paddingX={1}>
                <Text color={theme.primary} bold>{'>'} </Text>
                <TextInput
                    value={value}
                    onChange={onChange}
                    onSubmit={onSubmit}
                    placeholder={actualPlaceholder}
                />
            </Box>
        </Box>
    );
};
