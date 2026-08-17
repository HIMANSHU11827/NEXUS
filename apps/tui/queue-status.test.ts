import assert from 'node:assert/strict';
import {queueSnapshotLines} from './helpers.js';

const lines = queueSnapshotLines({
    pending: 2,
    scope: 'session',
    mode: 'embedded',
    worker: 'running',
    states: {queued: 1, leased: 1, completed: 9},
    tasks: [{id: 7, state: 'leased', attempts: 1, max_attempts: 3, summary: '  continue   safely  '}]
});

assert.equal(lines[0], 'queue (session): 2 pending · mode: embedded · worker: running');
assert.match(lines[1], /queued: 1/);
assert.equal(lines[2], 'unfinished:');
assert.equal(lines[3], '  #7 leased · 1/3 · continue safely');
assert.deepEqual(queueSnapshotLines({pending: 0, tasks: []}).slice(-1), ['unfinished: none']);
console.log('queue snapshot formatting: ok');
