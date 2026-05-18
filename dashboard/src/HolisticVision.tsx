import { useState, useRef, useCallback, useEffect } from 'react';

const API = 'http://127.0.0.1:8000';
type StreamState = 'idle' | 'connecting' | 'live' | 'error';
type VisionMode = 'objects' | 'segment' | 'face' | 'hand' | 'body';

const MODES: { id: VisionMode; label: string; icon: string; color: string; desc: string }[] = [
  { id: 'objects', label: 'Objects',   icon: '🎯', color: '#3b82f6', desc: 'YOLO11 object detection · 80 classes' },
  { id: 'segment', label: 'Segment',   icon: '✂️', color: '#8b5cf6', desc: 'YOLO11 instance segmentation masks'    },
  { id: 'face',    label: 'Face',      icon: '😶', color: '#f59e0b', desc: 'OpenCV Haar cascade face detector'     },
  { id: 'hand',    label: 'Hand',      icon: '✋', color: '#10b981', desc: 'RTMPose-M hand keypoints (21 kps)'     },
  { id: 'body',    label: 'Body',      icon: '🧍', color: '#ec4899', desc: 'RTMPose-M full-body skeleton (17 kps)' },
];

export default function HolisticVision() {
  const [streamState, setStreamState] = useState<StreamState>('idle');
  const [activeModes, setActiveModes] = useState<Set<VisionMode>>(new Set(['objects']));
  const [errorMsg, setErrorMsg]       = useState('');
  const imgRef   = useRef<HTMLImageElement>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const buildSrc = (modes: Set<VisionMode>) =>
    `${API}/api/vision/stream?modes=${[...modes].join(',')}&t=${Date.now()}`;

  const doStart = useCallback((modes: Set<VisionMode>) => {
    if (!imgRef.current || modes.size === 0) return;
    setStreamState('connecting');
    setErrorMsg('');
    imgRef.current.src = buildSrc(modes);
  }, []);

  const doStop = useCallback(async () => {
    if (retryRef.current) clearTimeout(retryRef.current);
    setStreamState('idle');
    setErrorMsg('');
    if (imgRef.current) imgRef.current.src = '';
    try { await fetch(`${API}/api/vision/stop`, { method: 'POST' }); } catch { /**/ }
  }, []);

  // Push mode set to backend without restarting stream (hot-swap)
  const pushModes = useCallback((modes: Set<VisionMode>) => {
    if (modes.size === 0) { doStop(); return; }
    fetch(`${API}/api/vision/modes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modes: [...modes] }),
    }).catch(() => {});
  }, [doStop]);

  const toggleMode = (id: VisionMode) => {
    setActiveModes(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      // If stream is live: hot-swap modes instantly (no restart)
      // If idle: just update state so START uses the right modes
      const running = streamState === 'live' || streamState === 'connecting';
      if (running) pushModes(next);
      return next;
    });
  };

  const allOn  = () => {
    const next = new Set<VisionMode>(MODES.map(m => m.id));
    setActiveModes(next);
    if (streamState === 'live' || streamState === 'connecting') pushModes(next);
  };
  const allOff = () => { doStop(); setActiveModes(new Set()); };

  const handleLoad  = () => { setStreamState('live'); setErrorMsg(''); };
  const handleError = () => {
    setStreamState('error');
    setErrorMsg('Stream failed — ensure FastAPI server is running and camera is connected.');
    retryRef.current = setTimeout(() => {
      if (imgRef.current && activeModes.size > 0) {
        imgRef.current.src = buildSrc(activeModes);
        setStreamState('connecting');
      }
    }, 4000);
  };
  useEffect(() => () => { if (retryRef.current) clearTimeout(retryRef.current); }, []);

  const isRunning  = streamState === 'live' || streamState === 'connecting';
  const badgeColor = { idle:'#666', connecting:'#fbbf24', live:'#4ade80', error:'#f87171' }[streamState];
  const badgeBg    = { idle:'rgba(100,100,100,0.1)', connecting:'rgba(251,191,36,0.1)', live:'rgba(74,222,128,0.1)', error:'rgba(248,113,113,0.1)' }[streamState];
  const badgeLabel = { idle:'OFFLINE', connecting:'LOADING…', live:'LIVE', error:'ERROR' }[streamState];

  return (
    <div style={{ display:'grid', gridTemplateRows:'auto auto 1fr', gap:'12px', padding:'18px 24px', height:'100%', overflow:'hidden', background:'#070707', color:'#fff' }}>
      <style>{`
        @keyframes vSpin  { to { transform: rotate(360deg); } }
        @keyframes vPulse { 0%,100%{opacity:1} 50%{opacity:0.35} }
        @keyframes vFade  { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        .vmode-btn:hover { filter: brightness(1.25); transform: translateY(-1px); }
      `}</style>

      {/* ── Header ── */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
        <div>
          <h2 style={{ margin:0, fontSize:'1.35rem', fontWeight:900, color:'var(--accent-blue)' }}>NEXUS VISION</h2>
          <div style={{ fontSize:'0.62rem', color:'#444', marginTop:'3px', letterSpacing:'1px' }}>
            HARDWARE EDGE · MJPEG · {activeModes.size} MODE{activeModes.size !== 1 ? 'S' : ''} ACTIVE
          </div>
        </div>
        <div style={{ display:'flex', gap:'8px', alignItems:'center' }}>
          <span style={{ fontSize:'0.62rem', fontWeight:800, color:badgeColor, background:badgeBg, padding:'4px 10px', borderRadius:'8px', letterSpacing:'1px' }}>{badgeLabel}</span>
          <button onClick={allOn}  style={{ background:'rgba(74,222,128,0.1)', color:'#4ade80', border:'1px solid rgba(74,222,128,0.25)', padding:'7px 14px', borderRadius:'8px', fontWeight:800, fontSize:'0.65rem', cursor:'pointer', letterSpacing:'1px' }}>ALL ON</button>
          <button onClick={allOff} style={{ background:'rgba(248,113,113,0.1)', color:'#f87171', border:'1px solid rgba(248,113,113,0.25)', padding:'7px 14px', borderRadius:'8px', fontWeight:800, fontSize:'0.65rem', cursor:'pointer', letterSpacing:'1px' }}>ALL OFF</button>
          {!isRunning ? (
            <button onClick={() => doStart(activeModes)} disabled={activeModes.size === 0}
              style={{ background: activeModes.size === 0 ? '#1a1a1a' : 'var(--accent-blue)', color: activeModes.size === 0 ? '#333' : '#fff', border:'none', padding:'8px 20px', borderRadius:'8px', fontWeight:800, fontSize:'0.7rem', cursor: activeModes.size === 0 ? 'not-allowed' : 'pointer', letterSpacing:'1px' }}>
              ▶ START
            </button>
          ) : (
            <button onClick={doStop}
              style={{ background:'rgba(248,113,113,0.15)', color:'#f87171', border:'1px solid rgba(248,113,113,0.3)', padding:'8px 20px', borderRadius:'8px', fontWeight:800, fontSize:'0.7rem', cursor:'pointer', letterSpacing:'1px' }}>
              ■ STOP
            </button>
          )}
        </div>
      </div>

      {/* ── Mode Toggles ── */}
      <div style={{ display:'flex', gap:'8px' }}>
        {MODES.map(m => {
          const on = activeModes.has(m.id);
          return (
            <button key={m.id} className="vmode-btn"
              onClick={() => toggleMode(m.id)}
              title={m.desc}
              style={{
                flex: 1, display:'flex', flexDirection:'column', alignItems:'center', gap:'6px',
                padding:'10px 6px', borderRadius:'10px', cursor:'pointer',
                border: on ? `1px solid ${m.color}66` : '1px solid rgba(255,255,255,0.06)',
                background: on ? `${m.color}15` : 'rgba(255,255,255,0.02)',
                boxShadow: on ? `0 0 16px ${m.color}20` : 'none',
                transition:'all 0.2s cubic-bezier(0.4,0,0.2,1)',
              }}>
              {/* Icon */}
              <div style={{ width:'34px', height:'34px', borderRadius:'50%', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'1.05rem', background: on ? `${m.color}22` : 'rgba(255,255,255,0.04)', border: on ? `1px solid ${m.color}44` : '1px solid transparent', transition:'all 0.2s' }}>
                {m.icon}
              </div>
              {/* Label */}
              <span style={{ fontSize:'0.56rem', fontWeight:800, color: on ? m.color : '#444', letterSpacing:'0.8px', textTransform:'uppercase', transition:'color 0.2s' }}>
                {m.label}
              </span>
              {/* ON/OFF pill */}
              <div style={{ fontSize:'0.5rem', fontWeight:900, color: on ? m.color : '#333', background: on ? `${m.color}18` : 'rgba(255,255,255,0.03)', border: `1px solid ${on ? m.color + '44' : 'rgba(255,255,255,0.06)'}`, padding:'1px 7px', borderRadius:'10px', letterSpacing:'1px', transition:'all 0.2s' }}>
                {on ? 'ON' : 'OFF'}
              </div>
            </button>
          );
        })}
      </div>

      {/* ── Video + Info ── */}
      <div style={{ display:'grid', gridTemplateColumns:'minmax(0,1fr) 260px', gap:'12px', minHeight:0, overflow:'hidden' }}>

        {/* Video */}
        <div style={{ position:'relative', borderRadius:'12px', overflow:'hidden', border:`1px solid ${isRunning ? '#3b82f644' : 'rgba(255,255,255,0.06)'}`, background:'#000', transition:'border-color 0.4s' }}>
          <img ref={imgRef} alt="Vision Stream"
            onLoad={handleLoad} onError={handleError}
            style={{ width:'100%', height:'100%', objectFit:'contain', display: streamState === 'live' ? 'block' : 'none' }}
          />
          {streamState !== 'live' && (
            <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', background:'radial-gradient(circle at center, rgba(59,130,246,0.07), rgba(0,0,0,0.95) 60%)' }}>
              <div style={{ textAlign:'center', padding:'20px', animation:'vFade 0.4s ease-out' }}>
                {streamState === 'idle' && (<>
                  <div style={{ fontSize:'2.8rem', marginBottom:'12px' }}>👁</div>
                  <div style={{ fontSize:'1.6rem', fontWeight:900, color:'#fff', marginBottom:'8px' }}>READY</div>
                  <div style={{ fontSize:'0.68rem', color:'#444', marginBottom:'20px' }}>
                    {activeModes.size === 0 ? 'Select at least one mode above, then press START.' : `${activeModes.size} mode${activeModes.size > 1 ? 's' : ''} selected · Press START to begin.`}
                  </div>
                  {activeModes.size > 0 && (
                    <button onClick={() => doStart(activeModes)}
                      style={{ background:'var(--accent-blue)', color:'#fff', border:'none', borderRadius:'10px', padding:'11px 24px', fontWeight:900, fontSize:'0.78rem', cursor:'pointer' }}>
                      CONNECT TO CAMERA
                    </button>
                  )}
                </>)}
                {streamState === 'connecting' && (<>
                  <div style={{ width:'44px', height:'44px', border:'3px solid rgba(59,130,246,0.15)', borderTopColor:'var(--accent-blue)', borderRadius:'50%', animation:'vSpin 0.9s linear infinite', margin:'0 auto 16px' }} />
                  <div style={{ fontSize:'0.78rem', color:'#aaa', fontWeight:700, letterSpacing:'1.5px' }}>INITIALISING STREAM…</div>
                  <div style={{ fontSize:'0.6rem', color:'#444', marginTop:'6px' }}>Loading models · Opening camera</div>
                </>)}
                {streamState === 'error' && (<>
                  <div style={{ fontSize:'2rem', marginBottom:'12px' }}>⚠️</div>
                  <div style={{ fontSize:'0.82rem', fontWeight:900, color:'#f87171', marginBottom:'8px' }}>STREAM FAILED</div>
                  <div style={{ fontSize:'0.65rem', color:'#777', lineHeight:1.7, marginBottom:'16px', maxWidth:'300px' }}>{errorMsg}</div>
                  <div style={{ fontSize:'0.58rem', color:'#444', marginBottom:'14px' }}>Auto-retrying in 4 s…</div>
                  <button onClick={() => { doStop(); setTimeout(() => doStart(activeModes), 200); }}
                    style={{ background:'var(--accent-blue)', color:'#fff', border:'none', borderRadius:'9px', padding:'9px 18px', fontWeight:900, fontSize:'0.7rem', cursor:'pointer' }}>
                    RETRY
                  </button>
                </>)}
              </div>
            </div>
          )}
          {/* Live HUD */}
          {streamState === 'live' && (<>
            <div style={{ position:'absolute', top:'10px', left:'10px', display:'flex', gap:'6px', alignItems:'center', background:'rgba(0,0,0,0.6)', padding:'3px 9px', borderRadius:'20px', backdropFilter:'blur(6px)' }}>
              <div style={{ width:'6px', height:'6px', borderRadius:'50%', background:'#f87171', animation:'vPulse 1.2s infinite' }} />
              <span style={{ fontSize:'0.55rem', fontWeight:900, color:'#fff', letterSpacing:'1.5px' }}>REC</span>
            </div>
            <div style={{ position:'absolute', top:'10px', right:'10px', display:'flex', gap:'4px', background:'rgba(0,0,0,0.6)', padding:'3px 9px', borderRadius:'20px', backdropFilter:'blur(6px)' }}>
              {MODES.filter(m => activeModes.has(m.id)).map(m => (
                <span key={m.id} style={{ fontSize:'0.9rem' }} title={m.label}>{m.icon}</span>
              ))}
            </div>
          </>)}
        </div>

        {/* Info panel */}
        <div style={{ display:'flex', flexDirection:'column', gap:'9px', minHeight:0, overflowY:'auto' }}>

          {/* Active modes summary */}
          <div style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:'10px', padding:'13px' }}>
            <div style={{ fontSize:'0.62rem', fontWeight:900, color:'#fff', letterSpacing:'1px', marginBottom:'10px' }}>ACTIVE MODULES</div>
            {MODES.map(m => {
              const on = activeModes.has(m.id);
              return (
                <div key={m.id} onClick={() => toggleMode(m.id)}
                  style={{ display:'flex', alignItems:'center', gap:'8px', padding:'6px 8px', borderRadius:'7px', cursor:'pointer', background: on ? `${m.color}10` : 'transparent', border: on ? `1px solid ${m.color}33` : '1px solid transparent', marginBottom:'4px', transition:'all 0.2s' }}>
                  <span style={{ fontSize:'0.9rem' }}>{m.icon}</span>
                  <span style={{ flex:1, fontSize:'0.65rem', fontWeight:700, color: on ? m.color : '#444' }}>{m.label}</span>
                  <div style={{ width:'28px', height:'15px', borderRadius:'8px', background: on ? m.color : 'rgba(255,255,255,0.08)', position:'relative', transition:'background 0.2s', flexShrink:0 }}>
                    <div style={{ position:'absolute', top:'2px', left: on ? '15px' : '2px', width:'11px', height:'11px', borderRadius:'50%', background:'#fff', transition:'left 0.2s' }} />
                  </div>
                </div>
              );
            })}
            <div style={{ display:'flex', gap:'6px', marginTop:'10px' }}>
              <button onClick={allOn}  style={{ flex:1, background:'rgba(74,222,128,0.08)', color:'#4ade80', border:'1px solid rgba(74,222,128,0.2)', padding:'6px', borderRadius:'7px', fontWeight:800, fontSize:'0.58rem', cursor:'pointer', letterSpacing:'1px' }}>ALL ON</button>
              <button onClick={allOff} style={{ flex:1, background:'rgba(248,113,113,0.08)', color:'#f87171', border:'1px solid rgba(248,113,113,0.2)', padding:'6px', borderRadius:'7px', fontWeight:800, fontSize:'0.58rem', cursor:'pointer', letterSpacing:'1px' }}>ALL OFF</button>
            </div>
          </div>

          {/* Stream info */}
          <div style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:'10px', padding:'13px' }}>
            <div style={{ fontSize:'0.62rem', fontWeight:900, color:'#fff', letterSpacing:'1px', marginBottom:'10px' }}>STREAM INFO</div>
            {[
              { k:'Status',    v: badgeLabel, c: badgeColor },
              { k:'Protocol',  v: 'MJPEG multipart', c: '#888' },
              { k:'Backend',   v: 'FastAPI + OpenCV', c: '#4ade80' },
              { k:'Browser',   v: 'Bypassed (native)', c: '#f87171' },
              { k:'Modes',     v: `${activeModes.size} / ${MODES.length} active`, c: '#aaa' },
            ].map(r => (
              <div key={r.k} style={{ display:'flex', justifyContent:'space-between', fontSize:'0.62rem', padding:'4px 0', borderTop:'1px solid rgba(255,255,255,0.04)', color:'#888' }}>
                <span>{r.k}</span><span style={{ color: r.c, fontWeight:700 }}>{r.v}</span>
              </div>
            ))}
          </div>

          {/* Models */}
          <div style={{ background:'rgba(255,255,255,0.025)', border:'1px solid rgba(255,255,255,0.06)', borderRadius:'10px', padding:'13px' }}>
            <div style={{ fontSize:'0.62rem', fontWeight:900, color:'#fff', letterSpacing:'1px', marginBottom:'10px' }}>LOCAL MODELS</div>
            {[
              { f:'yolo11n.pt',         mode:'objects', sz:'5.4 MB'  },
              { f:'yolo11n-seg.pt',     mode:'segment', sz:'5.9 MB'  },
              { f:'haarcascade (cv2)',  mode:'face',    sz:'built-in'},
              { f:'rtmpose hand5.onnx', mode:'hand',    sz:'52.5 MB' },
              { f:'rtmpose body7.onnx', mode:'body',    sz:'51.9 MB' },
            ].map(m => {
              const active = activeModes.has(m.mode as VisionMode);
              const mCfg   = MODES.find(x => x.id === m.mode)!;
              return (
                <div key={m.f} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', fontSize:'0.58rem', padding:'4px 0', borderTop:'1px solid rgba(255,255,255,0.04)' }}>
                  <span style={{ fontFamily:'monospace', color: active ? mCfg.color : '#555', fontWeight: active ? 800 : 400 }}>{m.f}</span>
                  <span style={{ color: active ? '#4ade80' : '#333' }}>{active ? `✓ ${m.sz}` : m.sz}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
