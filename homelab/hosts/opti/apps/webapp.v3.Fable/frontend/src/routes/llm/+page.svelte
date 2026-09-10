<script lang="ts">
  // Local LLM on the android phone. Two upstreams behind /api/llama/*: llama-ctl
  // (management, :8081) and llama-server (inference, :8080). The phone is often
  // offline by design, so every panel degrades to a plain "unreachable" line.
  import { createQuery } from '@tanstack/svelte-query';
  import { get } from '$lib/api/client';
  import StatusPanel from './_parts/StatusPanel.svelte';
  import AskPanel from './_parts/AskPanel.svelte';
  import RunbooksPanel from './_parts/RunbooksPanel.svelte';

  interface LlamaBattery { percentage?: number; temperature?: number; plugged?: string }
  interface LlamaStatus { model?: string; running?: boolean; battery?: LlamaBattery; [k: string]: unknown }
  // llama-ctl returns models as plain filename strings; older builds used {name,size}.
  interface ModelsResp { models?: (string | { name: string; size?: number })[]; current?: string }
  interface RunbooksResp { runbooks?: { name: string; bytes?: number }[] }

  const status = createQuery(() => ({
    queryKey: ['llama-status'],
    queryFn: () => get<LlamaStatus>('/api/llama/status', 10_000),
    refetchInterval: 60_000,
    retry: 0,
  }));
  const models = createQuery(() => ({
    queryKey: ['llama-models'],
    queryFn: () => get<ModelsResp>('/api/llama/models', 10_000),
    retry: 0,
  }));
  const runbooks = createQuery(() => ({
    queryKey: ['llama-runbooks'],
    queryFn: () => get<RunbooksResp>('/api/llama/runbooks', 10_000),
    retry: 0,
  }));
</script>

<div class="llm-page">
  <StatusPanel status={status.data} statusError={status.isError} models={models.data} />
  <AskPanel />
  <RunbooksPanel runbooks={runbooks.data?.runbooks ?? []} runbooksError={runbooks.isError} />
</div>
