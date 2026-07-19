/* eslint-disable @typescript-eslint/no-explicit-any */
import React from 'react';
import { Mic, Monitor, PlusCircle, Send, X, ChevronDown, Square } from 'lucide-react';
import type { ChatMessage, NexusState } from '../../types';

export interface ChatInputProps {
    messages: ChatMessage[];
    isDragging: boolean;
    setIsDragging: (val: boolean) => void;
    uploadedFiles: File[];
    setUploadedFiles: React.Dispatch<React.SetStateAction<File[]>>;
    screenSharing: boolean;
    screenShareError: string;
    stopScreenShare: () => void;
    ensureScreenShare: () => void;
    voiceListening: boolean;
    voiceError: string;
    voiceTranscript: string;
    stopVoiceConversation: () => void;
    startVoiceConversation: () => void;
    composerInputRef: React.RefObject<HTMLTextAreaElement | null>;
    brandName: string;
    inputValue: string;
    setInputValue: (val: string) => void;
    handleSend: () => void;
    isStreaming: boolean;
    stopCurrentTurn: () => void | Promise<void>;
    modelMenuRef: React.RefObject<HTMLDivElement | null>;
    showModelMenu: boolean;
    setShowModelMenu: (val: boolean) => void;
    selectedSessionProvider: string;
    setSelectedSessionProvider: (val: string) => void;
    state: NexusState | null;
}

export const ChatInput: React.FC<ChatInputProps> = ({
    messages, isDragging, setIsDragging, uploadedFiles, setUploadedFiles,
    screenSharing, screenShareError, stopScreenShare, ensureScreenShare,
    voiceListening, voiceError, voiceTranscript, stopVoiceConversation, startVoiceConversation,
    composerInputRef, brandName, inputValue, setInputValue, handleSend, isStreaming, stopCurrentTurn,
    modelMenuRef, showModelMenu, setShowModelMenu, selectedSessionProvider, setSelectedSessionProvider, state
}) => {
    return (
        <>
            <div className={`search-container composer-dock ${messages.length === 0 ? 'empty-composer' : ''}`}
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                    e.preventDefault();
                    setIsDragging(false);
                    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                        setUploadedFiles(prev => [...prev, ...Array.from(e.dataTransfer.files)]);
                    }
                }}
            >
                <div className={`search-bar-wrap ${isDragging ? 'dragging' : ''}`} style={isDragging ? { border: '1px dashed var(--accent-blue)', background: 'rgba(59, 130, 246, 0.05)' } : {}}>
                    {uploadedFiles.length > 0 && (
                        <div style={{ display: 'flex', gap: '10px', padding: '15px 15px 0 15px', flexWrap: 'wrap' }}>
                            {uploadedFiles.map((f, i) => (
                                <div key={i} style={{ background: '#1a1c22', border: '1px solid #2f333d', padding: '6px 10px', borderRadius: '999px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '5px', color: '#fff' }}>
                                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100px' }}>{f.name}</span>
                                    <X size={12} style={{ cursor: 'pointer' }} onClick={() => setUploadedFiles(prev => prev.filter((_, idx) => idx !== i))} />
                                </div>
                            ))}
                        </div>
                    )}

                    {(screenSharing || screenShareError) && (
                        <div className={`screen-share-status ${screenSharing ? 'active' : 'error'}`}>
                            <Monitor size={14} />
                            <span>{screenSharing ? 'Screen sharing active' : screenShareError}</span>
                            {screenSharing && (
                                <button type="button" onClick={stopScreenShare}>Stop</button>
                            )}
                        </div>
                    )}

                    {(voiceListening || voiceError) && (
                        <div className={`voice-status ${voiceListening ? 'active' : 'error'}`}>
                            <Mic size={14} />
                            <span>{voiceListening ? (voiceTranscript || 'Listening...') : voiceError}</span>
                            {voiceListening && (
                                <button type="button" onClick={stopVoiceConversation}>Stop</button>
                            )}
                        </div>
                    )}

                    <div className="composer-main-row">
                        <textarea
                            ref={composerInputRef}
                            className="main-input"
                            placeholder={`Type to ${brandName.trim() || 'NEXUS'}...`}
                            rows={1}
                            value={inputValue}
                            onChange={(e) => {
                                setInputValue(e.target.value);
                                e.target.style.height = 'auto';
                                e.target.style.height = e.target.scrollHeight + 'px';
                            }}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    if (isStreaming) stopCurrentTurn(); else handleSend();
                                    (e.target as any).style.height = 'auto';
                                }
                            }}
                            onPaste={(e) => {
                                if (e.clipboardData.files && e.clipboardData.files.length > 0) {
                                    setUploadedFiles(prev => [...prev, ...Array.from(e.clipboardData.files)]);
                                }
                            }}
                            style={{ resize: 'none', overflowY: 'hidden', minHeight: '28px', maxHeight: '160px', lineHeight: '1.5' }}
                        />
                        <div
                            className={`send-arrow ${isStreaming || inputValue || uploadedFiles.length > 0 ? 'active' : ''}`}
                            style={{ cursor: isStreaming || inputValue || uploadedFiles.length > 0 ? 'pointer' : 'default' }}
                            role="button"
                            tabIndex={0}
                            aria-label={isStreaming ? 'Stop current turn' : 'Send message'}
                            title={isStreaming ? 'Stop current turn' : 'Send message'}
                            onClick={() => isStreaming ? stopCurrentTurn() : handleSend()}
                            onKeyDown={(event) => {
                                if (event.key !== 'Enter' && event.key !== ' ') return;
                                event.preventDefault();
                                if (isStreaming) stopCurrentTurn(); else handleSend();
                            }}
                        >
                            {isStreaming ? <Square size={16} fill="currentColor" /> : <Send size={18} />}
                        </div>
                    </div>

                    <div className="input-footer">
                        <div className="action-icons">
                            <label className="icon-btn" style={{ cursor: 'pointer', color: '#888', transition: 'all 0.2s' }}>
                                <input type="file" multiple style={{ display: 'none' }} onChange={(e) => {
                                    if (e.target.files && e.target.files.length > 0) {
                                        setUploadedFiles(prev => [...prev, ...Array.from(e.target.files!)]);
                                    }
                                }} />
                                <PlusCircle size={20} className="hover-white" />
                            </label>
                            <button
                                type="button"
                                className={`icon-btn voice-btn ${voiceListening ? 'voice-active' : ''}`}
                                title={voiceListening ? 'Stop listening' : 'Start voice conversation'}
                                aria-label={voiceListening ? 'Stop voice conversation' : 'Start voice conversation'}
                                onClick={startVoiceConversation}
                            >
                                <Mic size={20} className="hover-white" />
                            </button>
                            <button
                                type="button"
                                className={`icon-btn screen-share-btn ${screenSharing ? 'screen-active' : ''}`}
                                title={screenSharing ? 'Screen share is active. Double-click to stop.' : 'Share entire screen'}
                                aria-label={screenSharing ? 'Screen share active' : 'Share entire screen'}
                                onClick={ensureScreenShare}
                                onDoubleClick={stopScreenShare}
                            >
                                <Monitor size={20} className="hover-white" />
                            </button>
                            <div className="model-selector-wrap" style={{ position: 'relative' }} ref={modelMenuRef}>
                                <div
                                    onClick={() => setShowModelMenu(!showModelMenu)}
                                    className="model-selector hover-bright"
                                >
                                    <span style={{ opacity: selectedSessionProvider ? 1 : 0.5 }}>
                                        {selectedSessionProvider || 'Select Model'}
                                    </span>
                                    <ChevronDown size={14} style={{ opacity: 0.4, transform: showModelMenu ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.3s cubic-bezier(0.4, 0, 0.2, 1)' }} />
                                </div>

                                {showModelMenu && (
                                    <div style={{
                                        position: 'absolute',
                                        bottom: 'calc(100% + 12px)',
                                        left: 0,
                                        width: '100%',
                                        background: '#111216',
                                        border: '1px solid #292c35',
                                        borderRadius: '16px',
                                        padding: '6px',
                                        zIndex: 9000,
                                        boxShadow: '0 18px 32px rgba(0, 0, 0, 0.32)',
                                        maxHeight: '280px',
                                        overflowY: 'auto'
                                    }} className="custom-scrollbar fade-in">
                                        {state?.provider_instances?.length === 0 ? (
                                            <div style={{ padding: '20px', fontSize: '0.7rem', color: '#444', textAlign: 'center', fontWeight: 800, letterSpacing: '1px' }}>
                                                NO MODELS ACTIVE
                                            </div>
                                        ) : (
                                            state?.provider_instances?.map((inst: any, idx: number) => (
                                                <div
                                                    key={idx}
                                                    onClick={() => {
                                                        setSelectedSessionProvider(inst.id);
                                                        setShowModelMenu(false);
                                                    }}
                                                    style={{
                                                        padding: '10px 14px',
                                                        borderRadius: '12px',
                                                        fontSize: '0.8rem',
                                                        cursor: 'pointer',
                                                        transition: 'all 0.2s',
                                                        marginBottom: '2px',
                                                        background: selectedSessionProvider === inst.id ? '#191d27' : 'transparent',
                                                        color: selectedSessionProvider === inst.id ? '#93c5fd' : '#a1a1aa',
                                                        fontWeight: selectedSessionProvider === inst.id ? 700 : 500
                                                    }}
                                                    className="dropdown-item-hover"
                                                >
                                                    {inst.id}
                                                </div>
                                            ))
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            {messages.length === 0 && (
                <div className="empty-prompt-row-wrap">
                    <div className="empty-prompt-label">Popular launches</div>
                <div className="empty-prompt-row">
                    {[
                        'Review recent changes',
                        'Find bugs',
                        'Run diagnostics',
                        'Search the codebase',
                        'Improve the UI',
                        'Plan next steps'
                    ].map(prompt => (
                        <button
                            key={prompt}
                            className="empty-prompt-chip"
                            onClick={() => setInputValue(prompt)}
                        >
                            {prompt}
                        </button>
                    ))}
                </div>
                </div>
            )}
        </>
    );
};
