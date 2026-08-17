import assert from 'node:assert/strict';
import {
    commandDefinitionFor,
    commandMatches,
    normalizeCommandRegistry
} from './helpers.js';

const commands = normalizeCommandRegistry({
    commands: [
        {
            name: 'status',
            description: 'System status overview',
            category: 'info',
            aliases: ['s'],
            args: {}
        },
        {
            name: '/help',
            description: 'Show all commands',
            category: 'general',
            aliases: ['/h'],
            args: {}
        },
        {name: '/status', description: 'duplicate must be ignored'}
    ]
});

assert.deepEqual(commands.map(command => command.name), ['/help', '/status']);
assert.equal(commandDefinitionFor('/s', commands)?.name, '/status');
assert.equal(commandDefinitionFor('/missing', commands), undefined);
assert.deepEqual(commandMatches('/sta', commands).map(command => command.name), ['/status']);
assert.deepEqual(commandMatches('/', commands).map(command => command.name), ['/help', '/status']);

console.log('Server command registry adapter tests passed');
