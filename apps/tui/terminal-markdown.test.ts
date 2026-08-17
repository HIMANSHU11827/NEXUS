import assert from 'node:assert/strict';
import {renderTerminalMarkdown} from './terminal-markdown.js';

const compact = 'Overview## Components| Component | Purpose | Status ||---|---|---|| **Backend** | FastAPI server | ✅ Working || **GUI** | React frontend | ✅ Working |';
const rendered = renderTerminalMarkdown(compact, 72);

assert.match(rendered, /┌─+┬─+┬─+┐/);
assert.match(rendered, /│ Backend/);
assert.match(rendered, /│ GUI/);
assert.doesNotMatch(rendered, /\*\*/);
assert(rendered.split('\n').every(line => line.length <= 72));
console.log('terminal markdown table: ok');
