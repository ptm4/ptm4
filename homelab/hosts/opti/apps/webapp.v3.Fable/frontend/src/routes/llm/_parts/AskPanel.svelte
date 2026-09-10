<script lang="ts">
  // Ask the homelab — runbook-grounded (or raw) Q&A against llama-server on the
  // phone. 185s upstream cap: CPU generation on the phone runs ~1.5-2.5 tok/s
  // even warm, so this is a plain async action with a busy flag, not a query.
  import { Send } from '@lucide/svelte';
  import { post } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import Markdown from '$lib/components/Markdown.svelte';

  interface AskResp { answer?: string; error?: string; ms?: number }
  interface ChatResp { choices?: { message?: { content?: string } }[] }

  let question = $state('');
  let answer = $state<string | null>(null);
  let grounded = $state(true);
  let busy = $state(false);

  async function ask() {
    const q = question.trim();
    if (!q || busy) return;
    busy = true;
    try {
      let text: string;
      if (grounded) {
        const r = await post<AskResp>('/api/llama/ask', { question: q }, 185_000);
        text = r.answer ?? r.error ?? '(no answer)';
      } else {
        const r = await post<ChatResp>('/api/llama/chat', {
          messages: [{ role: 'user', content: q }],
        }, 185_000);
        text = r.choices?.[0]?.message?.content ?? '(no answer)';
      }
      answer = text;
    } catch (e) {
      toast(`Ask failed: ${(e as Error).message}`, 'crit', { sticky: true });
    } finally {
      busy = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && question.trim()) ask();
  }
</script>

<section class="glass card">
  <div class="w-head">
    <span class="w-title">Ask the homelab</span>
    <span class="w-meta">
      <label class="t-dim">
        <input type="checkbox" bind:checked={grounded} /> runbook-grounded
      </label>
    </span>
  </div>
  <textarea
    class="llm-input"
    rows={3}
    placeholder={grounded ? 'e.g. how do I restart the VPN stack?' : 'raw prompt — no runbook context'}
    bind:value={question}
    onkeydown={onKeydown}
  ></textarea>
  <div class="w-actions">
    <button class="tbtn primary" disabled={busy || !question.trim()} onclick={ask}>
      <Send size={14} aria-hidden="true" /> {busy ? 'Thinking… (can take a minute)' : 'Ask'}
    </button>
  </div>
  {#if answer}<div class="llm-answer"><Markdown source={answer} /></div>{/if}
</section>
