export const cleanUserMessage = (text: string) => {
  if (!text) return '';
  return text.split('\n')
    .filter(line => {
      const trim = line.trim();
      if (trim.startsWith('/')) return false;
      if (trim.includes('[VOICE_MODE]')) return false;
      return true;
    })
    .join('\n')
    .trim();
};

export const cleanAssistantText = (text: string) => {
  if (!text) return '';
  const ansiEscape = String.fromCharCode(27);
  const noAnsi = text
    .replace(new RegExp(`${ansiEscape}\\[[0-9;]*m`, 'g'), '')
    .replace(/\\033\[[0-9;]*m/g, '');
  return noAnsi.split('\n')
    .filter(line => {
      const trim = line.trim();
      if (!trim) return true;
      if (/^NEXUS calling [a-zA-Z0-9_-]+(?: for .*?)?\.$/i.test(trim)) return false;
      if (/^[a-z_][a-z0-9_]*\(\s*\{.*\}\s*\)\s*$/i.test(trim)) return false;
      if (/^Call:\s*\{.*"action".*"params".*\}\}?$/i.test(trim)) return false;
      if (/^<\/?(function|function_name|parameters|max_results|query|url|path|command|target)>/i.test(trim)) return false;
      if (trim.startsWith('{') && trim.includes('"action"') && trim.includes('"params"')) return false;
      if (trim.includes('DSML')) return false;
      if (trim.includes('invoke name=')) return false;
      if (trim.includes('parameter name=')) return false;
      // Lifecycle tokens belong in Realtime Work, never in the assistant
      // conversation. The stream renderer may decorate them as a blockquote
      // with a lightning icon and bold markdown, so filter both forms.
      const lifecycleToken = trim
        .replace(/^>\s*/, '')
        .replace(/^(?:⚡|⚙️|🔄|✅|❌)\s*/u, '')
        .replace(/\*\*/g, '')
        .trim();
      if (/^\[(grounding|planning|inference(?:\s+\d+)?|auditing|executing|verifying|working|done|aborted|blocked)\]$/iu.test(lifecycleToken)) return false;
      if (/^<.*DSML.*>$/i.test(trim)) return false;
      if (/^<\/.*DSML.*>$/i.test(trim)) return false;
      if (/^<.*invoke name=.*>$/i.test(trim)) return false;
      if (/^<\/.*invoke>$/i.test(trim)) return false;
      if (/^<.*parameter name=.*>$/i.test(trim)) return false;
      if (/^<\/.*parameter>$/i.test(trim)) return false;
      if (/^\[(STARTING|NEXUS_ACTIVITY|THINKING|TOOL|SKILL|MCP|HIVE|SYSTEM|BASH|FILE|SEARCH|WEB|PROVIDER|WORKER|AGENT|NEXUS_BOOT|AUTO_OBSERVATION|ERROR|PROVIDER_ERROR|LAW_BLOCKED|PERMISSION_DENIED|NEXUS_SYSTEM_ERROR|ADVISORY|SUCCESS|EVOLUTION|ABORTED|INFERENCE)/i.test(trim)) return false;
      if (/^\[(ENGINEER|AUDITOR|ARCHITECT|RESEARCHER|LIBRARIAN|CODER|REVIEWER)\s+@\s+MISSION_/i.test(trim)) return false;
      if (trim.includes('@ MISSION_') && trim.includes('RESULT TASK-')) return false;
      if (/^\[THINKING: TURN \d+\]$/i.test(trim)) return false;
      if (/^TASK_COMPLETE$/i.test(trim)) return false;
      return true;
    })
    .join('\n')
    .trim();
};

// Backward-compatible aliases for older GUI imports.
export const formatUserMessageForChat = cleanUserMessage;
export const formatAssistantMessageForChat = cleanAssistantText;

export const cleanAssetDescription = (desc: unknown, _name?: unknown): string => {
  void _name;
  if (!desc) return '';
  return String(desc).trim();
};
