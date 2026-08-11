import React from 'react';
import assert from 'node:assert/strict';
import {NexusWelcomeLogo} from './welcome-logo.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

for (const [width, height] of [[100, 18], [40, 8], [20, 4]] as const) {
    const frame = await renderInkFrame(
        <NexusWelcomeLogo width={width} height={height} />,
        width,
        height
    );
    const lines = stripAnsi(frame).replace(/\r/g, '').split('\n');
    assert.ok(lines.some(line => line.trim().length > 0), `welcome mark is visible at ${width}x${height}`);
    assert.ok(lines.every(line => [...line].length <= width), `welcome mark fits ${width} columns`);
}

const large = await renderInkFrame(
    <NexusWelcomeLogo width={100} height={18} />,
    100,
    18
);
assert.ok(!large.includes('\u001B[40m'), 'large welcome logo does not paint a black background');
assert.ok(!large.includes('\u001B[48;2;0;0;0m'), 'large welcome logo has no true-color black surface');

const compact = stripAnsi(await renderInkFrame(
    <NexusWelcomeLogo width={40} height={8} />,
    40,
    8
));
assert.match(compact, /NEXUS/);
assert.match(compact, /Ask · edit · run · \/help/);

console.log('Welcome logo render tests passed');
