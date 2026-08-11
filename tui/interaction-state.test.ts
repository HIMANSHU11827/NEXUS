import assert from 'node:assert/strict';
import {isExplicitInspectorShortcut, moveQuestionSelection, nextInspectorPanel, questionChoiceCount, resolveQuestionSelection} from './interaction-state.js';

const question = {
    id: 'q1',
    prompt: 'How should NEXUS continue?',
    options: ['Fix the bug', 'Review the design'],
    allowCustom: true
};

assert.equal(nextInspectorPanel('workspace'), 'plan');
assert.equal(nextInspectorPanel('activity'), 'workspace');
assert.equal(nextInspectorPanel('question'), 'workspace');
assert.equal(isExplicitInspectorShortcut('o', true), true);
assert.equal(isExplicitInspectorShortcut('i', true), true);
assert.equal(isExplicitInspectorShortcut('o', false), false);
assert.equal(questionChoiceCount(question), 3);
assert.equal(moveQuestionSelection(question, 1, 1), 2);
assert.equal(moveQuestionSelection(question, 2, 1), 0);
assert.deepEqual(resolveQuestionSelection(question, 0), {kind: 'answer', answer: 'Fix the bug'});
assert.deepEqual(resolveQuestionSelection(question, 2), {kind: 'custom'});

console.log('Inspector and question interaction state: ok');
