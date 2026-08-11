import assert from 'node:assert/strict';
import {canStartTurn} from './helpers.js';

assert.equal(canStartTurn(false, 'refactor the terminal ui'), true);
assert.equal(canStartTurn(true, 'refactor the terminal ui'), false);
assert.equal(canStartTurn(true, '  another prompt  '), false);
assert.equal(canStartTurn(true, '/stop'), true);
assert.equal(canStartTurn(true, '/STOP  '), true);
assert.equal(canStartTurn(true, '/cancel'), true);

console.log('single-turn submission gate: ok');
