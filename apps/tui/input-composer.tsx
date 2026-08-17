/** Focused composer: the prompt remains the primary control. */
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
    width?: number;
}

export const InputComposer: React.FC<InputComposerProps> = ({value, onChange, onSubmit, placeholder, isBusy, showHints = true, width = 100}) => {
    const theme = getTheme();
    const compactHints = width < 78;
    return (
        <Box
            flexDirection="column"
            marginX={1}
            borderStyle="single"
            borderColor={isBusy ? theme.warning : theme.secondary}
            backgroundColor={theme.panelSoftBg}
        >
            <Box paddingX={1}>
                <Text color={theme.secondary} bold>{'>'} </Text>
                <Box flexGrow={1}>
                    <TextInput value={value} onChange={onChange} onSubmit={onSubmit} placeholder={placeholder || 'Message NEXUS...'} />
                </Box>
            </Box>
            {showHints && (
                <Box paddingX={1} justifyContent="space-between">
                    <Box>
                        {isBusy
                            ? <><Text color={theme.warning}>Run active</Text><Text color={theme.textDim}> · message held locally</Text></>
                            : <><Text color={theme.secondary}>Enter</Text><Text color={theme.textDim}> send</Text></>}
                        {!compactHints && <><Text color={theme.textMuted}>  ·  </Text><Text color={theme.secondary}>@</Text><Text color={theme.textDim}> attach</Text></>}
                        <Text color={theme.textMuted}>  ·  </Text>
                        <Text color={theme.secondary}>/</Text><Text color={theme.textDim}> commands</Text>
                    </Box>
                    <Box>
                        <Text color={theme.secondary}>Esc</Text><Text color={theme.textDim}> stop</Text>
                        {!compactHints && <><Text color={theme.textMuted}>  ·  </Text><Text color={theme.secondary}>Tab</Text><Text color={theme.textDim}> trace</Text><Text color={theme.textMuted}>  ·  </Text><Text color={theme.secondary}>Ctrl+O</Text><Text color={theme.textDim}> inspector</Text></>}
                    </Box>
                </Box>
            )}
        </Box>
    );
};
