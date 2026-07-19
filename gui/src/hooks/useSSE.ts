import { useRef, useCallback } from 'react';
import { getSseData, splitSseFrames } from '../utils/sse';

export type SSECallback = (data: unknown) => void;

export function useSSE() {
  const abortRef = useRef<AbortController | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  const connect = useCallback(async (
    url: string,
    onData: SSECallback,
    onDone?: () => void,
    onError?: (err: Error) => void,
    signal?: AbortSignal,
  ) => {
    abortRef.current?.abort();
    abortRef.current = new AbortController();
    const combinedSignal = signal
      ? AbortSignal.any([signal, abortRef.current.signal])
      : abortRef.current.signal;

    try {
      const res = await fetch(url, { signal: combinedSignal });
      if (!res.ok || !res.body) {
        throw new Error(`SSE connection failed: HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      readerRef.current = reader;
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsedFrames = splitSseFrames(buffer);
        buffer = parsedFrames.remainder;
        const frames = parsedFrames.frames;
        for (const frame of frames) {
          if (combinedSignal.aborted) return;
          const data = getSseData(frame).trim();
          if (!data || data === '[DONE]') continue;
          try {
            onData(JSON.parse(data));
          } catch {
            // skip malformed frames
          }
        }
      }
      if (buffer.trim()) {
        const data = getSseData(buffer).trim();
        if (data && data !== '[DONE]') {
          try {
            onData(JSON.parse(data));
          } catch { /* skip */ }
        }
      }
      onDone?.();
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  }, []);

  const disconnect = useCallback(() => {
    abortRef.current?.abort();
    readerRef.current?.cancel();
    readerRef.current = null;
    abortRef.current = null;
  }, []);

  return { connect, disconnect };
}
