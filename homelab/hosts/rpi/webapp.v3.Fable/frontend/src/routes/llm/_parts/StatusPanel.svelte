<script lang="ts">
  // llama-server status + model switcher. A status fetch error just means the
  // phone is asleep/unreachable — intermittent by design — so it renders calmly,
  // never as a crash.
  import { RefreshCw } from '@lucide/svelte';
  import { createMutation, useQueryClient } from '@tanstack/svelte-query';
  import { post } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';

  interface LlamaBattery { percentage?: number; temperature?: number; plugged?: string }
  interface LlamaStatus { model?: string; running?: boolean; battery?: LlamaBattery; [k: string]: unknown }
  // llama-ctl returns models as plain filename strings; older builds used {name,size}.
  interface ModelsResp { models?: (string | { name: string; size?: number })[]; current?: string }

  let { status, statusError, models }: {
    status: LlamaStatus | undefined;
    statusError: boolean;
    models: ModelsResp | undefined;
  } = $props();

  const qc = useQueryClient();

  const switchModel = createMutation(() => ({
    mutationFn: (name: string) => post('/api/llama/model', { name }, 25_000),
    onSuccess: () => {
      toast('Model switch requested — llama-server reloads on the phone (~2 min cold)', 'warn');
      qc.invalidateQueries({ queryKey: ['llama-status'] });
    },
    onError: (e: Error) => toast(`Model switch failed: ${e.message}`, 'crit'),
  }));

  let modelList = $derived(models?.models ?? []);
  let currentModel = $derived(models?.current ?? status?.model ?? '');
  let statusEntries = $derived(
    Object.entries(status ?? {}).filter(([k]) => !['model', 'running', 'battery'].includes(k)).slice(0, 6),
  );
  let battery = $derived(status?.battery);
</script>

<section class="glass card">
  <div class="w-head">
    <span class="w-title">llama-server</span>
    <span class="w-meta">
      <span class="pill" data-s={statusError ? 'warn' : 'ok'}>{statusError ? 'offline' : 'up'}</span>
    </span>
  </div>
  {#if statusError}
    <p class="t-dim">
      The phone is unreachable. It is intermittent by design — check it is on the
      LAN and llama-server is running (<span class="mono">ssh android</span>).
    </p>
  {:else}
    <div class="kv-rows">
      {#each statusEntries as [k, v] (k)}
        <div class="kv-row">
          <span>{k}</span>
          <span>{typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}</span>
        </div>
      {/each}
      {#if battery}
        <div class="kv-row">
          <span>battery</span>
          <span>
            {battery.percentage}% · {battery.temperature}°C{battery.plugged?.startsWith('PLUGGED') ? ' · charging' : ''}
          </span>
        </div>
      {/if}
    </div>
  {/if}
  {#if modelList.length > 0}
    <div class="w-actions">
      <select
        class="input"
        value={currentModel}
        disabled={switchModel.isPending}
        onchange={(e) => switchModel.mutate(e.currentTarget.value)}
      >
        {#each modelList as m (typeof m === 'string' ? m : m.name)}
          {@const name = typeof m === 'string' ? m : m.name}
          <option value={name}>{name}</option>
        {/each}
      </select>
      <button class="tbtn" onclick={() => qc.invalidateQueries({ queryKey: ['llama-status'] })}>
        <RefreshCw size={14} aria-hidden="true" /> Refresh
      </button>
    </div>
  {/if}
</section>
