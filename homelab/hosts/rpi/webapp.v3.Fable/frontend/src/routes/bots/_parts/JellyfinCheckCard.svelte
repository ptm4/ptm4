<script lang="ts">
  // jellyfin: connection check — probes the saved URL/API key on demand.
  import { createMutation } from '@tanstack/svelte-query';
  import { Plug } from '@lucide/svelte';
  import { get, ApiError } from '$lib/api/client';
  import type { JellyfinCheck } from '$lib/bots';

  function extraErrorMessage(e: unknown, fallback: string): string {
    return (e as ApiError)?.message ?? fallback;
  }

  let result = $state<{ text: string; ok: boolean } | null>(null);
  const check = createMutation(() => ({
    mutationFn: () => get<JellyfinCheck>('/api/jellyfin/check', 20_000),
    onSuccess: (d) => {
      if (d?.ok) {
        result = { ok: true, text: `Connected ✓ — ${d.server_name ?? 'Jellyfin'}${d.version ? ` (v${d.version})` : ''}` };
      } else {
        result = { ok: false, text: d?.error ?? 'Check failed — the bot reported an error.' };
      }
    },
    onError: (e: Error) => { result = { ok: false, text: extraErrorMessage(e, 'Check failed.') }; },
  }));
</script>

<section class="card bot-extra">
  <div class="w-head">
    <span class="w-title">Server connection</span>
  </div>
  {#if result}<p class={result.ok ? 't-dim' : 't-crit'}>{result.text}</p>{/if}
  <div class="w-actions">
    <button class="tbtn" disabled={check.isPending} onclick={() => check.mutate()}>
      <Plug size={14} aria-hidden="true" /> {check.isPending ? 'Checking…' : 'Test connection'}
    </button>
  </div>
  <p class="form-note t-dim">
    Probes the configured Jellyfin URL with the saved API key — save settings first if
    you just changed either.
  </p>
</section>
