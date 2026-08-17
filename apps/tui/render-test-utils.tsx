import React from 'react';
import {PassThrough} from 'node:stream';
import {render} from 'ink';

const ANSI_PATTERN = /[\u001B\u009B][[\]()#;?]*(?:(?:(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d/#&.:=?%@~_]+)*)?\u0007)|(?:(?:\d{1,4}(?:[;:]\d{0,4})*)?[\dA-PR-TZcf-nq-uy=><~]))/g;

export const stripAnsi = (value: string): string => value.replace(ANSI_PATTERN, '');

export const renderInkFrame = async (
    element: React.ReactElement,
    width: number,
    height: number
): Promise<string> => {
    const output = new PassThrough() as PassThrough & {
        columns: number;
        rows: number;
        isTTY: boolean;
        getColorDepth: () => number;
        hasColors: () => boolean;
    };
    output.columns = width;
    output.rows = height;
    output.isTTY = true;
    output.getColorDepth = () => 24;
    output.hasColors = () => true;

    const input = new PassThrough() as PassThrough & {
        isTTY: boolean;
        isRaw: boolean;
        setRawMode: (mode: boolean) => PassThrough;
        ref: () => PassThrough;
        unref: () => PassThrough;
    };
    input.isTTY = true;
    input.isRaw = false;
    input.setRawMode = (mode: boolean) => {
        input.isRaw = mode;
        return input;
    };
    input.ref = () => input;
    input.unref = () => input;

    const chunks: Buffer[] = [];
    output.on('data', chunk => chunks.push(Buffer.from(chunk)));
    const instance = render(element, {
        stdout: output as unknown as NodeJS.WriteStream,
        stdin: input as unknown as NodeJS.ReadStream,
        interactive: false,
        patchConsole: false,
        exitOnCtrlC: false
    });
    await instance.waitUntilRenderFlush();
    instance.unmount();
    await instance.waitUntilExit();
    return Buffer.concat(chunks).toString('utf8');
};
