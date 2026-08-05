import {appendToolOutput, isSyntheticAgentLifecycle, toolActivityIdentity, toolEventDeliveryIdentity} from './tool-call-state.js';

const start = {id: 'call-1', type: 'tool.started', status: 'running', tool: 'bash'};
const output = {id: 'call-1', type: 'command.stdout', status: 'running', stream: 'stdout', append: true, chunk: 'hello'};
const done = {id: 'call-1', type: 'tool.completed', status: 'success', output: 'done'};

if (toolActivityIdentity(start) !== toolActivityIdentity(output) || toolActivityIdentity(output) !== toolActivityIdentity(done)) {
    throw new Error('tool lifecycle events must share one activity identity');
}
if (toolEventDeliveryIdentity(start) === toolEventDeliveryIdentity(output)) {
    throw new Error('tool lifecycle updates must not be deduplicated as the same delivery');
}
if (appendToolOutput(appendToolOutput(undefined, 'hello'), ' world') !== 'hello world') {
    throw new Error('streamed tool output must accumulate');
}
if (appendToolOutput('hello world', 'world') !== 'hello world') {
    throw new Error('replayed output must not be duplicated');
}
if (!isSyntheticAgentLifecycle({kind: 'agent', type: 'run.completed'})) {
    throw new Error('unlinked run lifecycle events must be treated as non-Hive activity');
}
if (isSyntheticAgentLifecycle({kind: 'hive', type: 'subagent.completed', related_subagent: 'agent-1'})) {
    throw new Error('linked sub-agent events must remain visible');
}

console.log('tool call lifecycle state: ok');
