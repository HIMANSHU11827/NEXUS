import React from 'react';
import assert from 'node:assert/strict';
import {Box} from 'ink';
import {InputComposer} from './input-composer.js';
import {StatusBar} from './status-bar.js';
import {resolveTuiLayout} from './layout.js';
import {getFileName} from './helpers.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

assert.equal(getFileName('C:\\Users\\himan\\Desktop\\NEXUS AI\\providers\\fallback.ts'), 'fallback.ts');
assert.equal(getFileName('/workspace/tests/fallback.test.ts'), 'fallback.test.ts');

for (const width of [20, 39, 57, 58, 78]) {
    const height = 14;
    const layout = resolveTuiLayout(width, height);
    const frame = await renderInkFrame(
        <Box width={width} height={height} flexDirection="column">
            <Box flexGrow={1} />
            <InputComposer value="" onChange={() => {}} onSubmit={() => {}} isBusy showHints={layout.showComposerHints} width={layout.mainWidth} />
            <StatusBar
                width={layout.mainWidth}
                usage={{tokens: 2300, contextWindow: 8000, model: 'gpt-4.1'}}
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
        width,
        height
    );
    const plainLines = stripAnsi(frame).replace(/\r/g, '').split('\n');
    assert.ok(plainLines.every(line => [...line].length <= width), `render overflow at ${width} columns`);
    if (width < 58) assert.equal(layout.showComposerHints, false);
}

console.log('Compact Ink render tests passed');
