/**
 * @license
 * Copyright 2026 NEXUS AI
 * SPDX-License-Identifier: Apache-2.0
 */

import express, { Request, Response } from 'express';
import bodyParser from 'body-parser';
import { createTools } from './tools/tools.js';
import { McpContext } from './McpContext.js';
import { McpResponse } from './McpResponse.js';
import { ensureBrowserLaunched } from './browser.js';
import { logger } from './logger.js';
import { parseArguments } from './bin/nexus-omni-cli-options.js';
import { VERSION } from './version.js';

/**
 * Starts the NEXUS Omni Engine in Standalone HTTP Mode.
 */
export async function startStandaloneServer(port: number = 3000) {
    const app = express();
    app.use(bodyParser.json());

    // Initialize arguments and tools
    const args = parseArguments(VERSION, []);
    const tools = createTools(args);
    let context: McpContext | null = null;

    app.post('/action', async (req: Request, res: Response) => {
        const { tool, params } = req.body;
        logger(`NEXUS Standalone Action: ${tool}`, params);

        const targetTool = tools.find(t => t.name === tool) as any;
        if (!targetTool) {
            res.status(404).json({ error: `Tool ${tool} not found` });
            return;
        }

        try {
            const browser = await ensureBrowserLaunched({
                headless: args.headless,
                executablePath: args.executablePath,
                channel: args.channel as any,
                isolated: args.isolated ?? false,
                userDataDir: args.userDataDir,
                viewport: args.viewport,
                chromeArgs: (args.chromeArg ?? []).map(String),
                ignoreDefaultChromeArgs: (args.ignoreDefaultChromeArg ?? []).map(String),
                acceptInsecureCerts: args.acceptInsecureCerts,
                devtools: args.experimentalDevtools ?? false,
                enableExtensions: args.categoryExtensions,
                viaCli: true
            });

            if (!context || context.browser !== browser) {
                context = await McpContext.from(browser, logger, {
                    experimentalDevToolsDebugging: args.experimentalDevtools ?? false,
                    experimentalIncludeAllPages: args.experimentalIncludeAllPages,
                    performanceCrux: args.performanceCrux,
                });
            }

            const response = new McpResponse(args);
            
            if (targetTool.pageScoped) {
                const page = context.getSelectedMcpPage();
                response.setPage(page);
                await targetTool.handler(
                    { params, page }, 
                    response, 
                    context
                );
            } else {
                await targetTool.handler(
                    { params } as any, 
                    response, 
                    context
                );
            }

            const result = await response.handle(tool, context);
            res.json(result);
        } catch (error: any) {
            logger(`NEXUS Standalone Error: ${error.message}`);
            res.status(500).json({ error: error.message });
        }
    });

    app.get('/status', (req: Request, res: Response) => {
        res.json({ 
            status: 'NEXUS Omni Engine Standalone Active', 
            version: VERSION,
            tools: tools.length,
            mode: 'HTTP/REST'
        });
    });

    app.listen(port, () => {
        console.log(`\n[NEXUS OMNI ENGINE] Standalone Mode: http://localhost:${port}`);
        console.log(`Control via POST http://localhost:${port}/action { "tool": "os_click", "params": { ... } }`);
    });
}
