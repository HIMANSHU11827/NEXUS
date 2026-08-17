import assert from 'node:assert/strict';
import {questionFromToolEvent} from './helpers.js';

const question = questionFromToolEvent({
    event_type: 'tool.completed',
    status: 'success',
    tool: 'ask_question',
    output: '[QUESTION:{"id":"question-1","prompt":"Which option?","options":["A","B"],"allowCustom":true}]'
});

assert(question);
assert.match(question.id, /^question-/);
assert.deepEqual({...question, id: 'question-1'}, {
    id: 'question-1',
    prompt: 'Which option?',
    options: ['A', 'B'],
    allowCustom: true
});
assert.equal(questionFromToolEvent({status: 'success', tool: 'memory', output: '[QUESTION:{"prompt":"No","options":["x"]}]'}), null);
assert.equal(questionFromToolEvent({status: 'running', tool: 'ask_question', output: '[QUESTION:{"prompt":"No","options":["x"]}]'}), null);

console.log('tool question event parsing: ok');
