import {activeHiveAgents} from './live-agent-state.js';

const configuredCatalog = {
    agents: [
        {id: 'researcher', status: 'idle'},
        {id: 'engineer', status: 'idle'}
    ]
};
if (activeHiveAgents(configuredCatalog).length !== 0) {
    throw new Error('configured idle personas must not appear as live Hive agents');
}

const runningHive = {
    hives: [{
        status: 'running',
        agents: [{id: 'agent-1', persona: 'researcher', status: 'running', task: 'inspect TUI'}]
    }]
};
const live = activeHiveAgents(runningHive);
if (live.length !== 1 || live[0].name !== 'researcher') {
    throw new Error('running Hive agents must be projected into the live panel');
}

console.log('live agent projection: ok');
