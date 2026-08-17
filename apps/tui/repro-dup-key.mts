import {EventEmitter} from 'node:events';
import {render} from 'ink';
import React from 'react';

const originalError = console.error;
console.error = (...args: any[]) => {
    const message = String(args[0] || '');
    if (message.includes('same key')) {
        console.log('===CAPTURED (KEY=' + JSON.stringify(args[1]) + ')===');
        console.log(...args);
        console.log('===END===');
    }
    originalError(...args);
};

const mod: any = await import('./_repro-app.tsx');
const App: any = mod.App;

const stdin: any = new EventEmitter();
stdin.isTTY = false;
stdin.setRawMode = () => {};
stdin.setEncoding = () => {};
stdin.pause = () => {};
stdin.resume = () => {};
stdin.ref = () => {};
stdin.unref = () => {};
stdin.read = () => null;
stdin.destroy = () => {};

const stdout: any = new EventEmitter();
stdout.isTTY = true;
stdout.columns = 100;
stdout.rows = 30;
stdout.write = (chunk: string) => process.stdout.write(chunk);
stdout.on = (event: string, fn: any) => {
    if (event === 'resize') return stdout;
    return EventEmitter.prototype.on.call(stdout, event, fn);
};

process.on('uncaughtException', (err) => {
    console.log('UNCAUGHT:', String(err.message).slice(0, 150));
    process.exit(0);
});

console.log('MOUNTING isTTY=false...');
const instance = render(React.createElement(App), {stdin, stdout, exitOnCtrlC: false});
setTimeout(() => {
    instance.unmount();
    console.log('UNMOUNTED OK');
    process.exit(0);
}, 10000);
