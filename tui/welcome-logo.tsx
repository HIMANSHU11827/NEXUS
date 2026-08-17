/** Branded empty-session welcome surface. */
import React from 'react';
import {Box, Text} from 'ink';
import Gradient from 'ink-gradient';
import CFonts from 'cfonts';
import {THEME} from './helpers.js';

interface NexusWelcomeLogoProps {
    width: number;
    height: number;
}

const renderedWordmark = CFonts.render('NEXUS', {
    font: 'block',
    align: 'left',
    colors: ['system'],
    background: 'transparent',
    letterSpacing: 0,
    lineHeight: 1,
    space: false,
    maxLength: 0
});
const LARGE_WORDMARK = renderedWordmark ? renderedWordmark.string.trim() : 'NEXUS';

export const NexusWelcomeLogo = React.memo(({width, height}: NexusWelcomeLogoProps) => {
    const showLargeMark = width >= 64 && height >= 12;

    return (
        <Box
            width={width}
            height={height}
            flexDirection="column"
            justifyContent="flex-start"
            paddingX={showLargeMark ? 2 : 1}
            paddingTop={showLargeMark ? 2 : 1}
            backgroundColor={THEME.panelAltBg}
            overflow="hidden"
        >
            {showLargeMark ? (
                <Box flexDirection="column" alignItems="center">
                    <Gradient colors={['#4da3ff', '#72b7ff', '#ffb454', '#ff8a3d']}>
                        <Text backgroundColor={THEME.panelAltBg}>{LARGE_WORDMARK}</Text>
                    </Gradient>
                    <Text color="grey">Local-first autonomous engineering agent</Text>
                    <Text color="gray">Ask questions · edit files · run tools · /help for commands</Text>
                </Box>
            ) : (
                <Box flexDirection="column">
                    <Gradient colors={['#4da3ff', '#ffb454', '#ff8a3d']}>
                        <Text bold>NEXUS</Text>
                    </Gradient>
                    {height >= 4 && <Text color="grey">Ask · edit · run · /help</Text>}
                </Box>
            )}
        </Box>
    );
});
