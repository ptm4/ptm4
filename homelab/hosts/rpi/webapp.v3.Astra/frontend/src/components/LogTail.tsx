// Live log drawer for a runner. The dispatcher already writes <name>.log next to
// the reports; this polls the tail while it's open, so "Run now" shows progress
// instead of a 90-second silence.
import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from '../lib/api';
import { relTime } from '../lib/format';
import { Modal } from './Modal';

interface LogResp {
  name: string;
  exists: boolean;
  lines: string[];
  mtime?: string;
  size: number;
}

export function LogTail({ name, label, onClose }: { name: string; label: string; onClose: () => void }) {
  const bottom = useRef<HTMLDivElement>(null);

  const q = useQuery({
    queryKey: ['runner-log', name],
    queryFn: () => get<LogResp>(`/api/runners/${name}/log?lines=300`, 15_000),
    refetchInterval: 3000,
  });

  useEffect(() => { bottom.current?.scrollIntoView({ block: 'end' }); }, [q.dataUpdatedAt]);

  return (
    <Modal open onClose={onClose} title={`${label} — live log`} wide>
      {q.data && !q.data.exists && (
        <p className="t-dim">
          No log file for this runner yet. It writes one on its next run; the report
          itself updates either way.
        </p>
      )}
      {q.data?.exists && (
        <>
          <div className="t-dim log-meta">
            {(q.data.size / 1024).toFixed(1)} KB · updated {relTime(q.data.mtime)} · polling every 3s
          </div>
          <pre className="log-tail mono">
            {q.data.lines.join('\n')}
            <div ref={bottom} />
          </pre>
        </>
      )}
    </Modal>
  );
}
