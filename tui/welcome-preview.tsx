import React from 'react';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {Box} from 'ink';
import chalk from 'chalk';
import {NexusBanner} from './banner.js';
import {InputComposer} from './input-composer.js';
import {resolveTuiLayout} from './layout.js';
import {renderInkFrame} from './render-test-utils.js';
import {StatusBar} from './status-bar.js';
import {THEME} from './helpers.js';
import {NexusWelcomeLogo} from './welcome-logo.js';

const WIDTH = 110;
const HEIGHT = 30;
chalk.level = 3;
const layout = resolveTuiLayout(WIDTH, HEIGHT);

const frame = await renderInkFrame(
    <Box width={WIDTH} height={HEIGHT} flexDirection="column" backgroundColor={THEME.appBg}>
        <NexusBanner width={layout.chatContentWidth} connectionState="online" />
        <Box
            width={layout.chatContentWidth + 2}
            height={layout.chatViewportHeight}
            paddingX={1}
            backgroundColor={THEME.panelAltBg}
        >
            <NexusWelcomeLogo width={layout.chatContentWidth} height={layout.chatViewportHeight} />
        </Box>
        <InputComposer
            value=""
            onChange={() => {}}
            onSubmit={() => {}}
            placeholder="Message NEXUS..."
            showHints={layout.showComposerHints}
            width={layout.mainWidth}
        />
        <StatusBar
            width={layout.mainWidth}
            usage={{tokens: 0, contextWindow: 256000, model: 'deepseek/deepseek-chat'}}
            sandboxTier="normal"
            permissionMode="auto"
            voiceMode="off"
            voicePhase="off"
            mcpCount={0}
            agentCount={0}
            taskCount={0}
            connectionState="online"
        />
    </Box>,
    WIDTH,
    HEIGHT
);

const artifactDir = path.join(process.cwd(), 'artifacts');
await mkdir(artifactDir, {recursive: true});
const outputPath = path.join(artifactDir, 'tui-welcome-frame.ansi');
await writeFile(outputPath, frame);
process.stdout.write(`${outputPath}\n`);
