// Local LLM on the android phone. Two upstreams behind /api/llama/*: llama-ctl
// (management, :8081) and llama-server (inference, :8080). The phone is often
// offline by design, so every panel degrades to a plain "unreachable" line.
import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send, Save, Trash2, RefreshCw } from 'lucide-react';
import { get, post, put, del } from '../lib/api';
import { toast } from '../lib/toast';
import { Markdown } from '../components/Markdown';

interface LlamaStatus { model?: string; running?: boolean; [k: string]: unknown }
interface ModelsResp { models?: { name: string; size?: number }[]; current?: string }
interface RunbooksResp { runbooks?: { name: string; bytes?: number }[] }
interface AskResp { answer?: string; error?: string; ms?: number }
interface ChatResp { choices?: { message?: { content?: string } }[] }

export default function LlmPage() {
  const qc = useQueryClient();
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState<string | null>(null);
  const [grounded, setGrounded] = useState(true);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');

  const status = useQuery({
    queryKey: ['llama-status'],
    queryFn: () => get<LlamaStatus>('/api/llama/status', 10_000),
    refetchInterval: 60_000,
    retry: 0,
  });
  const models = useQuery({
    queryKey: ['llama-models'],
    queryFn: () => get<ModelsResp>('/api/llama/models', 10_000),
    retry: 0,
  });
  const runbooks = useQuery({
    queryKey: ['llama-runbooks'],
    queryFn: () => get<RunbooksResp>('/api/llama/runbooks', 10_000),
    retry: 0,
  });

  const switchModel = useMutation({
    mutationFn: (name: string) => post('/api/llama/model', { name }, 25_000),
    onSuccess: () => {
      toast('Model switch requested — llama-server reloads on the phone (~2 min cold)', 'warn');
      qc.invalidateQueries({ queryKey: ['llama-status'] });
    },
    onError: (e) => toast(`Model switch failed: ${(e as Error).message}`, 'crit'),
  });

  // 180s upstream cap: CPU generation on the phone runs ~1.5-2.5 tok/s even warm.
  const ask = useMutation({
    mutationFn: async (q: string) => {
      if (grounded) {
        const r = await post<AskResp>('/api/llama/ask', { question: q }, 185_000);
        return r.answer ?? r.error ?? '(no answer)';
      }
      const r = await post<ChatResp>('/api/llama/chat', {
        messages: [{ role: 'user', content: q }],
      }, 185_000);
      return r.choices?.[0]?.message?.content ?? '(no answer)';
    },
    onSuccess: (text) => setAnswer(text),
    onError: (e) => toast(`Ask failed: ${(e as Error).message}`, 'crit', { sticky: true }),
  });

  const saveRunbook = useMutation({
    mutationFn: ({ name, content }: { name: string; content: string }) =>
      put(`/api/llama/runbooks/${encodeURIComponent(name)}`, { content }, 15_000),
    onSuccess: () => {
      toast('Runbook saved', 'ok');
      qc.invalidateQueries({ queryKey: ['llama-runbooks'] });
      setEditing(null);
    },
    onError: (e) => toast(`Save failed: ${(e as Error).message}`, 'crit'),
  });

  const deleteRunbook = useMutation({
    mutationFn: (name: string) => del(`/api/llama/runbooks/${encodeURIComponent(name)}`, 15_000),
    onSuccess: () => {
      toast('Runbook deleted', 'ok');
      qc.invalidateQueries({ queryKey: ['llama-runbooks'] });
    },
    onError: (e) => toast(`Delete failed: ${(e as Error).message}`, 'crit'),
  });

  // Load a runbook's body when the editor opens.
  useEffect(() => {
    if (!editing) return;
    let alive = true;
    get<{ content?: string }>(`/api/llama/runbooks/${encodeURIComponent(editing)}`, 15_000)
      .then((d) => alive && setDraft(d.content ?? ''))
      .catch(() => alive && setDraft(''));
    return () => { alive = false; };
  }, [editing]);

  const offline = status.isError;

  return (
    <div className="llm-page">
      <section className="glass card">
        <div className="w-head">
          <span className="w-title">llama-server</span>
          <span className="w-meta">
            <span className="pill" data-s={offline ? 'warn' : 'ok'}>{offline ? 'offline' : 'up'}</span>
          </span>
        </div>
        {offline ? (
          <p className="t-dim">
            The phone is unreachable. It is intermittent by design — check it is on the
            LAN and llama-server is running (<span className="mono">ssh android</span>).
          </p>
        ) : (
          <div className="kv-rows">
            <div className="kv-row"><span>model</span><span className="mono">{status.data?.model ?? '—'}</span></div>
            {Object.entries(status.data ?? {})
              .filter(([k]) => !['model', 'running'].includes(k))
              .slice(0, 6)
              .map(([k, v]) => (
                <div className="kv-row" key={k}><span>{k}</span><span>{String(v)}</span></div>
              ))}
          </div>
        )}
        {(models.data?.models?.length ?? 0) > 0 && (
          <div className="w-actions">
            <select
              value={models.data?.current ?? status.data?.model ?? ''}
              onChange={(e) => switchModel.mutate(e.target.value)}
              disabled={switchModel.isPending}
            >
              {models.data!.models!.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
            </select>
            <button className="tb-btn" onClick={() => qc.invalidateQueries({ queryKey: ['llama-status'] })}>
              <RefreshCw /> Refresh
            </button>
          </div>
        )}
      </section>

      <section className="glass card">
        <div className="w-head">
          <span className="w-title">Ask the homelab</span>
          <span className="w-meta">
            <label className="t-dim">
              <input type="checkbox" checked={grounded} onChange={(e) => setGrounded(e.target.checked)} />
              {' '}runbook-grounded
            </label>
          </span>
        </div>
        <textarea
          className="llm-input"
          rows={3}
          value={question}
          placeholder={grounded ? 'e.g. how do I restart the VPN stack?' : 'raw prompt — no runbook context'}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && question.trim()) ask.mutate(question.trim());
          }}
        />
        <div className="w-actions">
          <button className="tb-btn primary" disabled={ask.isPending || !question.trim()}
            onClick={() => ask.mutate(question.trim())}>
            <Send /> {ask.isPending ? 'Thinking… (can take a minute)' : 'Ask'}
          </button>
        </div>
        {answer && <div className="llm-answer"><Markdown source={answer} /></div>}
      </section>

      <section className="glass card">
        <div className="w-head">
          <span className="w-title">Runbooks</span>
          <span className="w-meta">{runbooks.data?.runbooks?.length ?? 0} files</span>
        </div>
        {runbooks.isError && <p className="t-dim">llama-ctl unreachable.</p>}
        <div className="kv-rows">
          {(runbooks.data?.runbooks ?? []).map((r) => (
            <div className="kv-row" key={r.name}>
              <span className="mono">{r.name}</span>
              <span>
                <button className="link-btn" onClick={() => setEditing(r.name)}>edit</button>
                {' · '}
                <button className="link-btn" onClick={() => deleteRunbook.mutate(r.name)}>delete</button>
              </span>
            </div>
          ))}
        </div>
        {editing && (
          <div className="runbook-editor">
            <div className="w-head"><span className="w-title">{editing}</span></div>
            <textarea rows={16} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="w-actions">
              <button className="tb-btn primary" disabled={saveRunbook.isPending}
                onClick={() => saveRunbook.mutate({ name: editing, content: draft })}>
                <Save /> Save
              </button>
              <button className="tb-btn" onClick={() => setEditing(null)}>Cancel</button>
              <button className="tb-btn danger" onClick={() => { deleteRunbook.mutate(editing); setEditing(null); }}>
                <Trash2 /> Delete
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
