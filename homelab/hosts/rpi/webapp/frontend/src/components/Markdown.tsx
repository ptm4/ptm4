// Markdown rendering for report logs and LLM answers. v1 loaded marked off a CDN
// with no sanitization; v2 bundles it and pipes the output through DOMPurify —
// the only dangerouslySetInnerHTML in the app lives here, sanitized.
import { useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export function Markdown({ source }: { source: string }) {
  const html = useMemo(
    () => DOMPurify.sanitize(marked.parse(source, { async: false })),
    [source],
  );
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
