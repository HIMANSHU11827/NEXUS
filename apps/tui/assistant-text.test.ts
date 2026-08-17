import assert from 'node:assert/strict';
import {cleanVisibleAssistantText} from './helpers.js';

const raw = (
    "The grep isn't finding matches. Let me inspect the server file.\n"
    + '<｜｜DSML｜｜tool_calls>'
    + '<｜｜DSML｜｜invoke name="reading">'
    + '<｜｜DSML｜｜parameter name="path" string="true">server/__init__.py'
    + '</｜｜DSML｜｜parameter>'
    + '</｜｜DSML｜｜invoke>'
    + '</｜｜DSML｜｜tool_calls>'
);

assert.equal(
    cleanVisibleAssistantText(raw),
    "The grep isn't finding matches. Let me inspect the server file."
);
assert.doesNotMatch(cleanVisibleAssistantText(raw), /DSML|tool_calls|parameter/);
console.log('assistant transport markup cleanup: ok');
