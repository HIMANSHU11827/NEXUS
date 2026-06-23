import { useState } from 'react';
import { X, Eye, EyeOff, Cpu, Activity, ShieldCheck, ShieldAlert } from 'lucide-react';

export interface ProviderPanelProps {
   name: string;
   endpoint: string;
   apiKey: string;
   model: string;
   instanceName: string;
   editingInstanceId: string | null;
   providerCheck: any;
   setApiKey: (val: string) => void;
   setTargetModel: (val: string) => void;
   setProviderEndpoint: (val: string) => void;
   setInstanceName: (val: string) => void;
   onSave: () => void;
   onClose: () => void;
   onCheck: () => void;
}

export function ProviderPanel({
   name,
   endpoint,
   apiKey,
   model,
   instanceName,
   editingInstanceId,
   providerCheck,
   setApiKey,
   setTargetModel,
   setProviderEndpoint,
   setInstanceName,
   onSave,
   onClose,
   onCheck
}: ProviderPanelProps) {
   const [showKey, setShowKey] = useState(false);

   const title = editingInstanceId ? `Edit Provider Route: ${editingInstanceId}` : `Configure New ${name || 'LLM'} Route`;

   return (
      <div style={{
         position: 'fixed',
         inset: 0,
         background: 'rgba(9, 9, 11, 0.85)',
         backdropFilter: 'blur(8px)',
         display: 'flex',
         alignItems: 'center',
         justifyContent: 'center',
         zIndex: 9999,
         padding: '20px'
      }}>
         <div style={{
            background: '#18181b',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            borderRadius: '12px',
            width: '100%',
            maxWidth: '520px',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)',
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden',
            animation: 'modalFadeIn 0.2s cubic-bezier(0.16, 1, 0.3, 1)'
         }}>
            {/* Header */}
            <div style={{
               display: 'flex',
               alignItems: 'center',
               justifyContent: 'space-between',
               padding: '16px 20px',
               borderBottom: '1px solid rgba(255, 255, 255, 0.06)'
            }}>
               <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Cpu size={18} style={{ color: '#3b82f6' }} />
                  <span style={{ fontWeight: 700, fontSize: '1.05rem', color: '#fafafa' }}>{title}</span>
               </div>
               <button
                  onClick={onClose}
                  style={{
                     background: 'transparent',
                     border: 'none',
                     color: '#a1a1aa',
                     cursor: 'pointer',
                     padding: '4px',
                     display: 'flex',
                     alignItems: 'center',
                     justifyContent: 'center',
                     borderRadius: '6px',
                     transition: 'all 0.2s'
                  }}
                  onMouseEnter={(e) => {
                     e.currentTarget.style.background = 'rgba(255,255,255,0.06)';
                     e.currentTarget.style.color = '#ffffff';
                  }}
                  onMouseLeave={(e) => {
                     e.currentTarget.style.background = 'transparent';
                     e.currentTarget.style.color = '#a1a1aa';
                  }}
               >
                  <X size={18} />
               </button>
            </div>

            {/* Content / Form */}
            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', overflowY: 'auto', maxHeight: '70vh' }}>
               
               {/* Route ID */}
               <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 650, color: '#a1a1aa', letterSpacing: '0.5px' }}>ROUTE ID</label>
                  <input
                     type="text"
                     value={instanceName}
                     onChange={(e) => setInstanceName(e.target.value)}
                     disabled={!!editingInstanceId}
                     placeholder="e.g. openrouter_gpt4"
                     style={{
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        color: '#fafafa',
                        fontSize: '0.85rem',
                        outline: 'none',
                        transition: 'border-color 0.2s',
                        opacity: editingInstanceId ? 0.6 : 1
                     }}
                  />
                  {!editingInstanceId && (
                     <span style={{ fontSize: '0.68rem', color: '#71717a' }}>A unique identifier for this routing endpoint.</span>
                  )}
               </div>

               {/* API Endpoint */}
               <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 650, color: '#a1a1aa', letterSpacing: '0.5px' }}>API ENDPOINT</label>
                  <input
                     type="text"
                     value={endpoint}
                     onChange={(e) => setProviderEndpoint(e.target.value)}
                     placeholder="https://api.openai.com/v1"
                     style={{
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        color: '#fafafa',
                        fontSize: '0.85rem',
                        outline: 'none',
                        transition: 'border-color 0.2s'
                     }}
                  />
               </div>

               {/* API Key */}
               <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 650, color: '#a1a1aa', letterSpacing: '0.5px' }}>API KEY</label>
                  <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
                     <input
                        type={showKey ? 'text' : 'password'}
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        placeholder="sk-..."
                        style={{
                           background: 'rgba(255, 255, 255, 0.02)',
                           border: '1px solid rgba(255, 255, 255, 0.08)',
                           borderRadius: '8px',
                           padding: '10px 40px 10px 12px',
                           color: '#fafafa',
                           fontSize: '0.85rem',
                           outline: 'none',
                           width: '100%',
                           transition: 'border-color 0.2s'
                        }}
                     />
                     <button
                        type="button"
                        onClick={() => setShowKey(!showKey)}
                        style={{
                           position: 'absolute',
                           right: '10px',
                           background: 'transparent',
                           border: 'none',
                           color: '#a1a1aa',
                           cursor: 'pointer',
                           display: 'flex',
                           alignItems: 'center',
                           justifyContent: 'center',
                           padding: '4px'
                        }}
                     >
                        {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
                     </button>
                  </div>
               </div>

               {/* Model */}
               <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                  <label style={{ fontSize: '0.75rem', fontWeight: 650, color: '#a1a1aa', letterSpacing: '0.5px' }}>DEFAULT MODEL</label>
                  <input
                     type="text"
                     value={model}
                     onChange={(e) => setTargetModel(e.target.value)}
                     placeholder="e.g. gpt-4o, claude-3-5-sonnet"
                     style={{
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid rgba(255, 255, 255, 0.08)',
                        borderRadius: '8px',
                        padding: '10px 12px',
                        color: '#fafafa',
                        fontSize: '0.85rem',
                        outline: 'none',
                        transition: 'border-color 0.2s'
                     }}
                  />
               </div>

               {/* Test Status Info */}
               {providerCheck && (
                  <div style={{
                     padding: '12px 16px',
                     borderRadius: '8px',
                     background: providerCheck.status === 'running' ? 'rgba(59, 130, 246, 0.08)' : providerCheck.ok ? 'rgba(34, 197, 94, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                     border: `1px solid ${providerCheck.status === 'running' ? 'rgba(59, 130, 246, 0.16)' : providerCheck.ok ? 'rgba(34, 197, 94, 0.16)' : 'rgba(239, 68, 68, 0.16)'}`,
                     display: 'flex',
                     alignItems: 'center',
                     gap: '12px'
                  }}>
                     {providerCheck.status === 'running' ? (
                        <div className="spinner" style={{ width: '14px', height: '14px', border: '2px solid rgba(255,255,255,0.1)', borderTopColor: '#3b82f6', borderRadius: '50%', animation: 'spin 1s linear infinite' }} />
                     ) : providerCheck.ok ? (
                        <ShieldCheck size={16} style={{ color: '#4ade80' }} />
                     ) : (
                        <ShieldAlert size={16} style={{ color: '#f87171' }} />
                     )}
                     <span style={{ fontSize: '0.78rem', color: providerCheck.status === 'running' ? '#60a5fa' : providerCheck.ok ? '#4ade80' : '#f87171', fontWeight: 500 }}>
                        {providerCheck.message || (providerCheck.ok ? 'Connection valid.' : 'Connection check failed.')}
                     </span>
                  </div>
               )}

            </div>

            {/* Footer / Actions */}
            <div style={{
               display: 'flex',
               alignItems: 'center',
               justifyContent: 'space-between',
               padding: '16px 20px',
               borderTop: '1px solid rgba(255, 255, 255, 0.06)',
               background: 'rgba(0,0,0,0.08)'
            }}>
               <button
                  type="button"
                  onClick={onCheck}
                  disabled={providerCheck?.status === 'running'}
                  style={{
                     background: 'rgba(59, 130, 246, 0.1)',
                     border: '1px solid rgba(59, 130, 246, 0.2)',
                     borderRadius: '8px',
                     padding: '8px 14px',
                     color: '#60a5fa',
                     fontSize: '0.78rem',
                     fontWeight: 600,
                     cursor: 'pointer',
                     display: 'flex',
                     alignItems: 'center',
                     gap: '6px',
                     transition: 'all 0.2s',
                     opacity: providerCheck?.status === 'running' ? 0.6 : 1
                  }}
                  onMouseEnter={(e) => {
                     if (providerCheck?.status !== 'running') e.currentTarget.style.background = 'rgba(59, 130, 246, 0.18)';
                  }}
                  onMouseLeave={(e) => {
                     e.currentTarget.style.background = 'rgba(59, 130, 246, 0.1)';
                  }}
               >
                  <Activity size={14} />
                  Test Route
               </button>

               <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                     type="button"
                     onClick={onClose}
                     style={{
                        background: 'transparent',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: '8px',
                        padding: '8px 14px',
                        color: '#cbd5e1',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 0.2s'
                     }}
                     onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                     }}
                     onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                     }}
                  >
                     Cancel
                  </button>
                  <button
                     type="button"
                     onClick={onSave}
                     style={{
                        background: '#3b82f6',
                        border: 'none',
                        borderRadius: '8px',
                        padding: '8px 16px',
                        color: '#fafafa',
                        fontSize: '0.78rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        boxShadow: '0 4px 12px rgba(59, 130, 246, 0.24)',
                        transition: 'all 0.2s'
                     }}
                     onMouseEnter={(e) => {
                        e.currentTarget.style.background = '#2563eb';
                     }}
                     onMouseLeave={(e) => {
                        e.currentTarget.style.background = '#3b82f6';
                     }}
                  >
                     Save Configuration
                  </button>
               </div>
            </div>
         </div>
         <style>{`
            @keyframes modalFadeIn {
               from { opacity: 0; transform: scale(0.97); }
               to { opacity: 1; transform: scale(1); }
            }
            @keyframes spin {
               to { transform: rotate(360deg); }
            }
         `}</style>
      </div>
   );
}
