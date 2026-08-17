export interface SseFrame {
  event?: string
  id?: string
  data: string
}

export function parseSseStream(reader: ReadableStreamDefaultReader<Uint8Array>, onFrame: (frame: SseFrame) => void, onDone: () => void, onError: (err: string) => void) {
  const decoder = new TextDecoder()
  let buffer = ''
  let current: Partial<SseFrame> = {}

  function processLine(line: string) {
    if (line === '') {
      if (current.data !== undefined || current.event) {
        onFrame({ event: current.event, id: current.id, data: current.data || '' })
      }
      current = {}
      return
    }
    if (line.startsWith('event: ')) {
      current.event = line.slice(7).trim()
    } else if (line.startsWith('id: ')) {
      current.id = line.slice(4).trim()
    } else if (line.startsWith('data: ')) {
      const chunk = line.slice(6)
      current.data = current.data !== undefined ? current.data + '\n' + chunk : chunk
    } else if (line.startsWith('data:')) {
      current.data = current.data !== undefined ? current.data + '\n' : ''
    }
  }

  async function pump() {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        processLine(line.replace('\r', ''))
      }
    }
    if (buffer.trim()) {
      processLine(buffer.replace('\r', ''))
    }
    if (current.data !== undefined || current.event) {
      onFrame({ event: current.event, id: current.id, data: current.data || '' })
    }
    onDone()
  }

  pump().catch(err => onError(err.message))
}
