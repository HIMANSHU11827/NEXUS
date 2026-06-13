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
      if (trim.startsWith('```')) return false;
      if (/^\[(STARTING|NEXUS_ACTIVITY|THINKING|TOOL|SKILL|MCP|HIVE|SYSTEM|BASH|FILE|SEARCH|WEB|PROVIDER|WORKER|AGENT|NEXUS_BOOT|AUTO_OBSERVATION|ERROR|PROVIDER_ERROR|LAW_BLOCKED|PERMISSION_DENIED|NEXUS_SYSTEM_ERROR|ADVISORY|SUCCESS|EVOLUTION|ABORTED)/i.test(trim)) return false;
      if (/^\[(ENGINEER|AUDITOR|ARCHITECT|RESEARCHER|LIBRARIAN|CODER|REVIEWER)\s+@\s+MISSION_/i.test(trim)) return false;
      if (trim.includes('@ MISSION_') && trim.includes('RESULT TASK-')) return false;
      if (/^\[THINKING: TURN \d+\]$/i.test(trim)) return false;
      if (/^TASK_COMPLETE$/i.test(trim)) return false;
      return true;
    })
    .join('\n')
    .trim();
};
