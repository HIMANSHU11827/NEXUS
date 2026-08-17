import Editor from '@monaco-editor/react'
import { useRef } from 'react'

interface MonacoEditorProps {
  value: string
  onChange: (value: string) => void
  language: string
  path: string
}

const languageMap: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  py: 'python',
  rs: 'rust',
  go: 'go',
  css: 'css',
  scss: 'scss',
  html: 'html',
  json: 'json',
  toml: 'toml',
  yml: 'yaml',
  yaml: 'yaml',
  md: 'markdown',
  xml: 'xml',
  txt: 'plaintext',
  log: 'plaintext',
  sh: 'shell',
  bash: 'shell',
  zsh: 'shell',
  ps1: 'powershell',
  c: 'c',
  cpp: 'cpp',
  h: 'c',
  hpp: 'cpp',
  java: 'java',
  kt: 'kotlin',
  swift: 'swift',
  php: 'php',
  rb: 'ruby',
  sql: 'sql',
}

function getLanguageFromPath(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() || ''
  return languageMap[ext] || 'plaintext'
}

export default function MonacoEditor({ value, onChange, language, path }: MonacoEditorProps) {
  const editorRef = useRef<any>(null)

  const detectedLanguage = language || getLanguageFromPath(path)

  return (
    <div className="w-full h-full">
      <Editor
        height="100%"
        language={detectedLanguage}
        value={value}
        onChange={(value) => onChange(value || '')}
        theme="vs"
        path={path}
        options={{
          minimap: { enabled: true },
          fontSize: 14,
          lineNumbers: 'on',
          roundedSelection: false,
          scrollBeyondLastLine: false,
          readOnly: false,
          automaticLayout: true,
          tabSize: 2,
          wordWrap: 'on',
          folding: true,
          bracketPairColorization: {
            enabled: true,
          },
          guides: {
            bracketPairs: true,
            indentation: true,
          },
          suggest: {
            showKeywords: true,
            showSnippets: true,
          },
          quickSuggestions: {
            other: true,
            comments: true,
            strings: true,
          },
        }}
        onMount={(editor) => {
          editorRef.current = editor
        }}
      />
    </div>
  )
}
