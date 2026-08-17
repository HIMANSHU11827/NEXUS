import React from 'react';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import chalk from 'chalk';
import {Box, Text} from 'ink';
import {NEXUS_BLUE_BRIGHT} from './theme.js';
import {QuestionPanelBody} from './details-panel.js';
import {renderInkFrame} from './render-test-utils.js';
import {THEME} from './helpers.js';

chalk.level = 3;
const WIDTH = 52;
const HEIGHT = 28;
const question = {
    id: 'question-preview',
    prompt: 'How should NEXUS proceed with the provider fallback fix?',
    options: ['Implement the fix now', 'Review the proposed changes first', 'Run focused tests before editing'],
    allowCustom: true
};

const frame = await renderInkFrame(
    <Box
        width={WIDTH}
        height={HEIGHT}
        flexDirection="column"
        borderStyle="single"
        borderColor={THEME.borderSoft}
        paddingX={1}
        backgroundColor={THEME.panelBg}
    >
        <Box justifyContent="space-between" marginBottom={1}>
            <Text bold color={NEXUS_BLUE_BRIGHT}>NEXUS</Text>
            <Text color="blueBright" bold>QUESTION</Text>
        </Box>
        <QuestionPanelBody question={question} selectedIndex={1} customActive={false} width={WIDTH - 2} />
    </Box>,
    WIDTH,
    HEIGHT
);

const artifactDir = path.join(process.cwd(), 'artifacts');
await mkdir(artifactDir, {recursive: true});
const outputPath = path.join(artifactDir, 'tui-question-frame.ansi');
await writeFile(outputPath, frame);
process.stdout.write(`${outputPath}\n`);
