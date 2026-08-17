import assert from 'node:assert/strict';
import {isExplicitInspectorShortcut, moveQuestionSelection, nextInspectorPanel, panelModeAfterActivitySelection, QuestionAnswerQueue, questionChoiceCount, resolveQuestionAnswerSubmission, resolveQuestionSelection} from './interaction-state.js';

const question = {
    id: 'q1',
    prompt: 'How should NEXUS continue?',
    options: ['Fix the bug', 'Review the design'],
    allowCustom: true
};

assert.equal(nextInspectorPanel('workspace'), 'plan');
assert.equal(nextInspectorPanel('activity'), 'workspace');
assert.equal(nextInspectorPanel('question'), 'workspace');
assert.equal(panelModeAfterActivitySelection('workspace', 'plan'), 'plan');
assert.equal(panelModeAfterActivitySelection('activity', 'plan'), 'plan');
assert.equal(panelModeAfterActivitySelection('activity', 'tool'), 'workspace');
assert.equal(panelModeAfterActivitySelection('hive', 'tool'), 'hive');
assert.deepEqual(resolveQuestionAnswerSubmission('  option A  ', true), {kind: 'queue', answer: 'option A'});
assert.deepEqual(resolveQuestionAnswerSubmission('  option A  ', false), {kind: 'submit', answer: 'option A'});
assert.deepEqual(resolveQuestionAnswerSubmission('   ', false), {kind: 'ignore'});
const answerQueue = new QuestionAnswerQueue();
answerQueue.enqueue('  option A  ');
assert.equal(answerQueue.take(), 'option A', 'queued answer is released once after turn cleanup');
assert.equal(answerQueue.take(), null, 'released answer is not replayed twice');
answerQueue.enqueue('option B');
answerQueue.clear();
assert.equal(answerQueue.take(), null, 'cancellation clears queued answers');
assert.equal(isExplicitInspectorShortcut('o', true), true);
assert.equal(isExplicitInspectorShortcut('i', true), true);
assert.equal(isExplicitInspectorShortcut('o', false), false);
assert.equal(questionChoiceCount(question), 3);
assert.equal(moveQuestionSelection(question, 1, 1), 2);
assert.equal(moveQuestionSelection(question, 2, 1), 0);
assert.deepEqual(resolveQuestionSelection(question, 0), {kind: 'answer', answer: 'Fix the bug'});
assert.deepEqual(resolveQuestionSelection(question, 2), {kind: 'custom'});

console.log('Inspector and question interaction state: ok');
