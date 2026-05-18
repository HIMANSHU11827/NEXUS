/**
 * @license
 * Copyright 2026 NEXUS AI
 * SPDX-License-Identifier: Apache-2.0
 */

import { execSync } from 'node:child_process';
import { zod } from '../third_party/index.js';
import { ToolCategory } from './categories.js';
import { defineTool } from './ToolDefinition.js';
import { logger } from '../logger.js';

function toPy(val: any, fallback?: any): string {
    if (val === undefined || val === null) {
        if (fallback !== undefined) return String(fallback);
        return 'None';
    }
    if (typeof val === 'string') return `"${val.replace(/"/g, '\\"')}"`;
    if (typeof val === 'boolean') return val ? 'True' : 'False';
    return String(val);
}

export const py_exec = defineTool({
    name: 'py_exec',
    description: 'Execute raw Python code for UI automation debugging.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        code: zod.string().describe('The Python code to execute')
    },
    handler: async (request, response) => {
        const { code } = request.params;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

/**
 * Executes Python-based UI automation logic with robust escaping and base64 transfer.
 */
function runPyAutoGUI(code: string) {
    try {
        // Find minimum indentation to preserve relative structure
        const lines = code.split('\n');
        // Remove leading/trailing empty lines
        while (lines.length > 0 && lines[0].trim() === '') lines.shift();
        while (lines.length > 0 && lines[lines.length - 1].trim() === '') lines.pop();
        
        // Add 4 spaces of indentation to every line to fit in our try/except block
        const indentedCode = lines.map(line => '    ' + line).join('\n');

        const fullPythonCode = `
import pyautogui
import sys
import os

pyautogui.FAILSAFE = True
try:
${indentedCode}
    sys.stdout.write("Execution Successful")
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
`;
        const base64Code = Buffer.from(fullPythonCode).toString('base64');
        const command = `python -c "import base64; exec(base64.b64decode('${base64Code}').decode('utf-8'))"`;
        
        logger(`Executing OMNI-UI OS Action: \n${indentedCode}`);
        const result = execSync(command, { timeout: 30000 }).toString();
        return result || 'Action executed successfully';
    } catch (error: any) {
        const errorMsg = error.stderr?.toString() || error.message;
        logger(`OMNI-UI OS Error: ${errorMsg}`);
        throw new Error(`OS Automation Error: ${errorMsg}`);
    }
}

export const os_click = defineTool({
    name: 'os_click',
    description: 'Click mouse at OS level (Desktop/Apps).',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        x: zod.number().optional().describe('The x coordinate'),
        y: zod.number().optional().describe('The y coordinate'),
        button: zod.enum(['left', 'right', 'middle']).optional().default('left').describe('Mouse button to click'),
        clicks: zod.number().optional().default(1).describe('Number of clicks'),
        interval: zod.number().optional().default(0.1).describe('Interval between clicks')
    },
    handler: async (request, response) => {
        const { x, y, button, clicks, interval } = request.params;
        const ix = x !== undefined ? Math.round(x) : 'None';
        const iy = y !== undefined ? Math.round(y) : 'None';
        const shotPath = `workspace/observations/click_${Date.now()}.png`;
        
        const code = `
import os
pyautogui.click(x=${ix}, y=${iy}, button=${toPy(button)}, clicks=${toPy(clicks, 1)}, interval=${toPy(interval, 0.1)})
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
sys.stdout.write("\\n[VISUAL_VERIFICATION]: Screenshot saved at ${shotPath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_type = defineTool({
    name: 'os_type',
    description: 'Type text at OS level (Desktop/Apps).',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        text: zod.string().describe('The text to type'),
        interval: zod.number().optional().default(0.01).describe('Interval between characters')
    },
    handler: async (request, response) => {
        const { text, interval } = request.params;
        const code = `pyautogui.write(${toPy(text)}, interval=${toPy(interval, 0.01)})`;
        let res = runPyAutoGUI(code);
        
        // 👁️ [INTEGRATED_VISION]: Automatic result verification
        try {
            const shotPath = `workspace/observations/type_${Date.now()}.png`;
            const shotCode = `
import os
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
`;
            runPyAutoGUI(shotCode);
            res = `${res}\n[VISUAL_VERIFICATION]: Typing complete. Screenshot saved at ${shotPath}.`;
        } catch (e) {}
        
        response.appendResponseLine(res);
    }
});

export const os_move = defineTool({
    name: 'os_move',
    description: 'Move mouse to specific coordinates.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        x: zod.number().describe('The x coordinate'),
        y: zod.number().describe('The y coordinate'),
        duration: zod.number().optional().default(0.2).describe('Duration of the movement in seconds')
    },
    handler: async (request, response) => {
        const { x, y, duration } = request.params;
        const ix = Math.round(x);
        const iy = Math.round(y);
        const shotPath = `workspace/observations/move_${Date.now()}.png`;
        const code = `
import os
pyautogui.moveTo(x=${ix}, y=${iy}, duration=${toPy(duration, 0.2)})
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
sys.stdout.write("\\n[VISUAL_VERIFICATION]: Screenshot saved at ${shotPath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_hotkey = defineTool({
    name: 'os_hotkey',
    description: 'Perform a keyboard hotkey combination (e.g., win+r, ctrl+c, alt+tab).',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        keys: zod.array(zod.string()).describe('The keys to press simultaneously (e.g., ["win", "r"])'),
        interval: zod.number().optional().default(0.1).describe('Interval between key presses')
    },
    handler: async (request, response) => {
        const { keys, interval } = request.params;
        const pyKeys = keys.map(k => `"${k}"`).join(', ');
        const code = `pyautogui.hotkey(${pyKeys}, interval=${toPy(interval, 0.1)})`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_scroll = defineTool({
    name: 'os_scroll',
    description: 'Scroll the mouse wheel.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        clicks: zod.number().describe('Number of scroll clicks (positive for up, negative for down)'),
        x: zod.number().optional().describe('X coordinate to scroll at'),
        y: zod.number().optional().describe('Y coordinate to scroll at')
    },
    handler: async (request, response) => {
        const { clicks, x, y } = request.params;
        const ix = x !== undefined ? Math.round(x) : 'None';
        const iy = y !== undefined ? Math.round(y) : 'None';
        const shotPath = `workspace/observations/scroll_${Date.now()}.png`;
        const code = `
import os
pyautogui.scroll(${Math.round(clicks)}, x=${ix}, y=${iy})
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
sys.stdout.write("\\n[VISUAL_VERIFICATION]: Screenshot saved at ${shotPath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_drag = defineTool({
    name: 'os_drag',
    description: 'Drag the mouse to a specific location while holding a button.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        x: zod.number().describe('Target x coordinate'),
        y: zod.number().describe('Target y coordinate'),
        button: zod.enum(['left', 'right', 'middle']).optional().default('left').describe('Mouse button to hold'),
        duration: zod.number().optional().default(0.5).describe('Duration of the drag in seconds')
    },
    handler: async (request, response) => {
        const { x, y, button, duration } = request.params;
        const ix = Math.round(x);
        const iy = Math.round(y);
        const shotPath = `workspace/observations/drag_${Date.now()}.png`;
        const code = `
import os
pyautogui.dragTo(x=${ix}, y=${iy}, button=${toPy(button)}, duration=${toPy(duration, 0.5)})
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
sys.stdout.write("\\n[VISUAL_VERIFICATION]: Screenshot saved at ${shotPath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_press = defineTool({
    name: 'os_press',
    description: 'Press a single key (e.g., esc, space, f1).',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        key: zod.string().describe('The key to press'),
        presses: zod.number().optional().default(1).describe('Number of times to press'),
        interval: zod.number().optional().default(0.1).describe('Interval between presses')
    },
    handler: async (request, response) => {
        const { key, presses, interval } = request.params;
        const shotPath = `workspace/observations/press_${Date.now()}.png`;
        const code = `
import os
pyautogui.press(${toPy(key)}, presses=${toPy(presses, 1)}, interval=${toPy(interval, 0.1)})
dir_name = os.path.dirname("${shotPath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${shotPath}")
sys.stdout.write("\\n[VISUAL_VERIFICATION]: Screenshot saved at ${shotPath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_info = defineTool({
    name: 'os_info',
    description: 'Get OS screen resolution and system information.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: true,
    },
    schema: {},
    handler: async (request, response) => {
        const code = `
size = pyautogui.size()
sys.stdout.write(f"Resolution: {size.width}x{size.height}, Platform: {sys.platform}, OS: {os.name}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_list_windows = defineTool({
    name: 'os_list_windows',
    description: 'List all open windows with their titles and status.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: true,
    },
    schema: {},
    handler: async (request, response) => {
        const code = `
try:
    import pygetwindow as gw
    windows = gw.getAllWindows()
    res = []
    for w in windows:
        if w.title:
            res.append(f"{w.title} (x={w.left}, y={w.top}, w={w.width}, h={w.height}, visible={w.visible})")
    sys.stdout.write("\\n".join(res))
except ImportError:
    sys.stdout.write("pygetwindow not installed. Install with: pip install pygetwindow")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_window_action = defineTool({
    name: 'os_window_action',
    description: 'Perform an action on a window (focus, minimize, maximize, close).',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: false,
    },
    schema: {
        title: zod.string().describe('The title of the window (partial match ok)'),
        action: zod.enum(['focus', 'minimize', 'maximize', 'close']).describe('The action to perform')
    },
    handler: async (request, response) => {
        const { title, action } = request.params;
        const code = `
try:
    import pygetwindow as gw
    wins = gw.getWindowsWithTitle("${title.replace(/"/g, '\\"')}")
    if not wins:
        sys.stderr.write(f"No window found with title: ${title}")
        sys.exit(1)
    w = wins[0]
    if "${action}" == "focus":
        w.activate()
    elif "${action}" == "minimize":
        w.minimize()
    elif "${action}" == "maximize":
        w.maximize()
    elif "${action}" == "close":
        w.close()
    sys.stdout.write(f"Action ${action} performed on {w.title}")
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});

export const os_screenshot = defineTool({
    name: 'os_screenshot',
    description: 'Take a screenshot of the entire OS desktop.',
    annotations: {
        category: ToolCategory.EMULATION,
        readOnlyHint: true,
    },
    schema: {
        path: zod.string().optional().describe('The local path to save the screenshot')
    },
    handler: async (request, response) => {
        const path = request.params.path || 'workspace/os_screenshot.png';
        const safePath = path.replace(/\\/g, '/');
        const code = `
dir_name = os.path.dirname("${safePath}")
if dir_name and not os.path.exists(dir_name):
    os.makedirs(dir_name)
pyautogui.screenshot("${safePath}")
`;
        const res = runPyAutoGUI(code);
        response.appendResponseLine(res);
    }
});
