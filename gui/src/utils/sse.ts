export function getSseEventType(frame: string): string {
  return frame
    .replace(/\r/g, '')
    .split('\n')
    .find(line => line.startsWith('event:'))
    ?.slice(6)
    .trim() || 'message';
}

export function getSseData(frame: string): string {
  return frame
    .replace(/\r/g, '')
    .split('\n')
    .filter(line => line.startsWith('data:'))
    .map(line => line.replace(/^data:\s?/, ''))
    .join('\n');
}

export function splitSseFrames(buffer: string): { frames: string[]; remainder: string } {
  const normalized = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  const parts = normalized.split('\n\n');
  return {
    frames: parts.slice(0, -1),
    remainder: parts[parts.length - 1] || '',
  };
}
