import React from 'react';
import assert from 'node:assert/strict';
import {Box} from 'ink';
import {PlanPanelBody, QuestionPanelBody} from './details-panel.js';
import {renderInkFrame, stripAnsi} from './render-test-utils.js';

const question = {
    id: 'question-preview',
    prompt: 'How should NEXUS proceed with the provider fallback fix?',
    options: ['Implement the fix now', 'Review the proposed changes first'],
    allowCustom: true
};

const frame = await renderInkFrame(
    <Box width={52} height={24} flexDirection="column">
        <QuestionPanelBody question={question} selectedIndex={1} customActive={false} width={52} />
    </Box>,
    52,
    24
);
const plain = stripAnsi(frame).replace(/\r/g, '');
assert.match(plain, /NEXUS NEEDS YOUR INPUT/);
assert.match(plain, /Review the proposed changes first/);
assert.match(plain, /Write a different answer/);
assert.match(plain, /Enter choose/);
assert.ok(plain.split('\n').every(line => [...line].length <= 52), 'question panel fits its inspector width');

console.log('Question panel render tests passed');

const planFrame = await renderInkFrame(
    <Box width={52} height={16} flexDirection="column">
        <PlanPanelBody
            items={[
                {id: 'step-1', index: 1, description: 'Inspect the workspace', status: 'done'},
                {id: 'step-2', index: 2, description: 'Create the game', status: 'running'},
                {id: 'step-3', index: 3, description: 'Run a local preview', status: 'pending'}
            ]}
            status="planning"
            expanded={true}
        />
    </Box>,
    52,
    16
);
const planPlain = stripAnsi(planFrame).replace(/\r/g, '');
assert.match(planPlain, /Advanced Planning/);
assert.match(planPlain, /Inspect the workspace/);
assert.match(planPlain, /Run a local preview/);
assert.ok(planPlain.split('\n').every(line => [...line].length <= 52), 'plan panel fits its inspector width');

console.log('Plan panel render tests passed');
