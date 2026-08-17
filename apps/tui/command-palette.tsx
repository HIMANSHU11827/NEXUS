/**
 * Nexus TUI v3.0 — Command Palette
 * Slash-command completion palette shown above the input box.
 */
import React from 'react';
import {Box, Text} from 'ink';
import {THEME, type CommandDefinition} from './helpers.js';

interface CommandPaletteProps {
    matches: CommandDefinition[];
    selectedIndex: number;
}

export const CommandPalette = React.memo(({matches, selectedIndex}: CommandPaletteProps) => {
    if (matches.length === 0) return null;

    return (
        <Box flexDirection="column" marginX={1} marginBottom={0} borderStyle="single" borderColor={THEME.border} backgroundColor={THEME.paletteBg}>
            {matches.map((command, index) => {
                const selected = index === selectedIndex;
                return (
                    <Box key={command.name} backgroundColor={selected ? '#ffb27c' : THEME.paletteBg}>
                        <Box width={18}>
                            <Text color={selected ? 'black' : 'white'} bold>{command.name}</Text>
                        </Box>
                        <Text color={selected ? 'black' : 'grey'}>{command.description}</Text>
                    </Box>
                );
            })}
            <Box justifyContent="flex-end" backgroundColor={THEME.paletteBg}>
                <Text color="grey30">tab complete  ↑↓ select  enter run</Text>
            </Box>
        </Box>
    );
});
