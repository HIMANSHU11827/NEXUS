import assert from 'node:assert/strict';
import {parseQuestionMarker, stripQuestionMarkers} from './helpers.js';

const marker = '[QUESTION:{"prompt":"Which option?","options":["A","B"],"allowCustom":true}]';
const parsed = parseQuestionMarker(`Before ${marker} after`);
assert(parsed);
assert.deepEqual(parsed.options, ['A', 'B']);
assert.equal(stripQuestionMarkers(`Before ${marker} after`), 'Before  after');

console.log('nested question marker parsing: ok');
