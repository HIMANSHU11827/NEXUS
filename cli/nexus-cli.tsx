import React, {useState, useEffect} from 'react';
import {render, Box, Text, useApp} from 'ink';
import TextInput from 'ink-text-input';
import Spinner from 'ink-spinner';
import axios from 'axios';
import Gradient from 'ink-gradient';
import BigText from 'ink-big-text';

// ── [NEXUS CONFIG]
const API_BASE = "http://localhost:8000/api";

interface Message {
    role: string;
    content: string;
}

interface FileStatus {
    name: string;
    status: string;
}

const Header = React.memo(() => (
    <Box flexDirection="column" borderStyle="single" borderColor="grey30" paddingX={1} marginBottom={0}>
        <Box justifyContent="space-between" alignItems="center">
            <Box alignItems="center">
                <Text color="magenta" bold>◈ NEXUS </Text>
                <Text color="white" bold>SOVEREIGN </Text>
                <Text color="grey30">v2.0 </Text>
            </Box>
            <Box>
                <Text color="grey">KERNEL: </Text>
                <Text color="cyan" bold>STABLE</Text>
                <Text color="grey30"> | </Text>
                <Text color="grey">LATENCY: </Text>
                <Text color="green">14ms</Text>
            </Box>
        </Box>
    </Box>
));

const Banner = React.memo(() => (
    <Box justifyContent="center" marginY={1} flexDirection="column" alignItems="center">
        <Gradient colors={['#4285F4', '#9B51E0']}>
            <Text bold>{`
  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
            `}</Text>
        </Gradient>
        <Box flexDirection="column" marginTop={0} alignItems="flex-start" width={50}>
            <Text color="grey" dimColor>Tips for getting started:</Text>
            <Text color="grey" dimColor>1. Ask questions, edit files, or run commands.</Text>
            <Text color="grey" dimColor>2. Be specific for the best results.</Text>
            <Text color="grey" dimColor>3. <Text color="magenta">/help</Text> for more information.</Text>
        </Box>
    </Box>
));

const HistoryItem = ({msg}: {msg: Message}) => (
    <Box marginBottom={0} flexDirection="column">
        <Box>
            <Text bold color={msg.role === 'user' ? "blue" : "magenta"}>
                {msg.role === 'user' ? "> " : "✦ "}
            </Text>
            <Text wrap="wrap" color={msg.role === 'system' ? "red" : "white"}>
                {msg.content}
            </Text>
        </Box>
    </Box>
);

const App = () => {
    const [input, setInput] = useState('');
    const [history, setHistory] = useState<Message[]>([]);
    const [activities, setActivities] = useState<string[]>([]);
    const [touchedFiles, setTouchedFiles] = useState<FileStatus[]>([]);
    const [lastChange, setLastChange] = useState<string>('');
    const [isThinking, setIsThinking] = useState(false);
    const [width, setWidth] = useState(process.stdout.columns || 100);
    const {exit} = useApp();

    useEffect(() => {
        const handleResize = () => setWidth(process.stdout.columns);
        process.stdout.on('resize', handleResize);
        return () => { process.stdout.off('resize', handleResize); };
    }, []);

    const isWide = width > 110;

    const handleSubmit = async (value: string) => {
        if (!value) return;
        if (value.toLowerCase() === 'exit' || value.toLowerCase() === 'quit') exit();

        const userMsg: Message = { role: 'user', content: value };
        setHistory(prev => [...prev, userMsg]);
        setInput('');
        setIsThinking(true);

        try {
            const response = await fetch(`${API_BASE}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt: value, session_id: "default" })
            });

            if (!response.body) throw new Error("No response body");
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            
            let assistantContent = '';
            setHistory(prev => [...prev, { role: 'assistant', content: '' }]);

            while (true) {
                const { done, value: chunk } = await reader.read();
                if (done) break;
                
                const text = decoder.decode(chunk);
                
                // ── [INTELLIGENCE_EXTRACTION]: Robust marker parsing
                if (text.includes("[TOOL_START:")) {
                    try {
                        const markerMatch = text.match(/\[TOOL_START:([^:]+):(.*)\]/);
                        if (markerMatch) {
                            const [_, toolName, paramsStr] = markerMatch;
                            const params = JSON.parse(paramsStr);
                            
                            // Track file changes for sidebar
                            if (toolName === 'file_edit' || toolName === 'write_file') {
                                const filename = params.filename || params.path;
                                if (filename) {
                                    const fileNameOnly = filename.split(/[/\\]/).pop() || filename;
                                    setTouchedFiles(prev => {
                                        const filtered = prev.filter(f => f.name !== fileNameOnly);
                                        return [{name: fileNameOnly, status: 'MODIFIED'}, ...filtered.slice(0, 2)];
                                    });
                                    setActivities(prev => [`Δ Modifying ${fileNameOnly}`, ...prev.slice(0, 2)]);
                                    
                                    if (params.new_string || params.content) {
                                        const content = params.new_string || params.content;
                                        setLastChange(content.split('\n').slice(0, 8).join('\n'));
                                    }
                                }
                            } else {
                                setActivities(prev => [`⚙ Executing ${toolName}`, ...prev.slice(0, 2)]);
                            }
                        }
                    } catch(e) {
                        // Silent fail for malformed markers during streaming
                    }
                }

                // Append to visible content only if it's not a pure marker chunk
                if (!text.startsWith("[TOOL_START:") && !text.startsWith("[TOOL_END:")) {
                    assistantContent += text;
                    setHistory(prev => {
                        const newHist = [...prev];
                        newHist[newHist.length - 1] = { role: 'assistant', content: assistantContent };
                        return newHist;
                    });
                }
                
                setIsThinking(false);
            }
        } catch (err) {
            setHistory(prev => [...prev, { role: 'system', content: "SYSTEM_ERROR: Kernel API unreachable." }]);
        } finally {
            setIsThinking(false);
        }
    };

    return (
        <Box flexDirection="column" paddingX={1} minHeight={25} borderStyle="bold" borderColor="grey30">
            <Header />
            <Banner />
            
            {/* 🌌 ADAPTIVE COMMAND AREA */}
            <Box flexDirection="row" flexGrow={1} minHeight={15}>
                
                {/* LEFT: STRATEGIC COMMAND */}
                <Box flexDirection="column" flexGrow={1} padding={1}>
                    {history.map((msg, i) => (
                        <HistoryItem key={`hist-${i}`} msg={msg} />
                    ))}
                    {isThinking && (
                        <Box flexDirection="column">
                            <Text italic color="grey">Responding with nexus-sovereign-v2</Text>
                            <Box>
                                <Text color="magenta">✦ </Text>
                                <Text italic color="cyan"><Spinner type="dots" /> aligning neural weights...</Text>
                            </Box>
                        </Box>
                    )}
                </Box>

                {/* RIGHT: CODE INTELLIGENCE (50/50 Split) */}
                {isWide && (
                    <Box 
                        flexDirection="column" 
                        flexGrow={1} 
                        borderStyle="single" 
                        borderColor="grey30" 
                        paddingX={2}
                    >
                        <Box marginBottom={0} borderStyle="single" borderColor="magenta">
                            <Text bold color="magenta"> ◈ LIVE CODE DELTA </Text>
                        </Box>
                        
                        <Box flexGrow={1} padding={1}>
                            {lastChange === '' ? (
                                <Box height="100%" alignItems="center" justifyContent="center">
                                    <Text color="grey30" italic>Awaiting neural stream...</Text>
                                </Box>
                            ) : (
                                <Text color="green" dimColor>{lastChange}</Text>
                            )}
                        </Box>
                    </Box>
                )}
            </Box>

            {/* APP STATS (GEMINI STYLE) */}
            <Box justifyContent="space-between" paddingX={1} marginY={1}>
                <Text color="blue">~\{process.cwd().split(/[/\\]/).pop()}</Text>
                <Box>
                    <Text color="red">no sandbox </Text>
                    <Text color="grey30">(see /docs)</Text>
                </Box>
                <Text color="magenta">auto</Text>
            </Box>

            {/* PROMPT BOX */}
            <Box paddingX={1} borderStyle="round" borderColor="grey" marginBottom={0}>
                <Box marginRight={1}>
                    <Text color="blue" bold>{"> "}</Text>
                </Box>
                <TextInput value={input} onChange={setInput} onSubmit={handleSubmit} placeholder="Type your message or @path/to/file" />
            </Box>
        </Box>
    );
};

render(<App />);
