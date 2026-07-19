import assert from 'node:assert/strict';
import {detectChoiceQuestion, formatChoiceQuestionForChat} from './choice-question.js';

const inlineNumbered = `Got it, Himanshu.Here's a question with options:**What would you like me to focus on next?**1. **Build something new** — Start a fresh project or feature.2. **Fix a bug** — Track down and permanently resolve a current issue.3. **Improve an existing system** — Optimize, refactor, or extend something already in place.4. **Research** — Dig into a topic, tool, or technology you're curious about.5. **Clean up or organize** — Audit the project, logs, or workspace for better structure.6. **Just chat** — Ask me anything or give me general direction.Pick a number, or tell me what you're thinking.`;

const question = detectChoiceQuestion(inlineNumbered);
assert(question);
assert.equal(question.options.length, 6);
assert.match(question.prompt, /What would you like me to focus on next\?/);
assert.match(question.options[0], /Build something new/);
assert.match(question.options[5], /Just chat/);
assert.doesNotMatch(question.options[5], /Pick a number/);
assert.match(formatChoiceQuestionForChat(question), /\n1\. Build something new/);

console.log('choice question parser: ok');
