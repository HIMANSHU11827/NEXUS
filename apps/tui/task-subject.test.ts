import {strict as assert} from 'node:assert';
import {cleanTaskSubject, taskItemsFromWorkItems} from './helpers.js';

assert.equal(
    cleanTaskSubject('[pending1bfa1eefea4] Categorize all modified files'),
    'Categorize all modified files'
);
assert.equal(
    cleanTaskSubject('[task_e1bfa1eefea4] Categorize all modified files'),
    'Categorize all modified files'
);
assert.equal(cleanTaskSubject('pending approval from user'), 'pending approval from user');
assert.equal(cleanTaskSubject('Review the new files'), 'Review the new files');

const freshSessionTasks = taskItemsFromWorkItems([
    {task_id: 'task-current', title: '[task_e1bfa1eefea4] Current session task', status: 'planned'}
]);
assert.deepEqual(freshSessionTasks, [{
    id: 'task-current',
    subject: 'Current session task',
    status: 'pending',
    startedAt: undefined
}]);
assert.deepEqual(taskItemsFromWorkItems([]), []);

console.log('task subject cleanup tests passed');
