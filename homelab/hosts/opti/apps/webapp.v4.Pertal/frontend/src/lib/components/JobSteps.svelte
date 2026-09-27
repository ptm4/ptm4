<script lang="ts">
  import { Check, X, LoaderCircle, Minus, Circle } from '@lucide/svelte';
  import type { Job } from '$lib/types';
  let { job }: { job: Job } = $props();
</script>

<ol class="steps">
  {#each job.steps as s (s.key)}
    <li class={s.status}>
      <span class="ico">
        {#if s.status === 'ok'}<Check size={14} />
        {:else if s.status === 'failed'}<X size={14} />
        {:else if s.status === 'running'}<LoaderCircle size={14} class="spin" />
        {:else if s.status === 'skipped'}<Minus size={14} />
        {:else}<Circle size={10} />{/if}
      </span>
      <div class="txt">
        <div>{s.label}{#if s.ms != null}<span class="faint num"> · {(s.ms / 1000).toFixed(1)}s</span>{/if}</div>
        {#if s.output}<pre>{s.output}</pre>{/if}
      </div>
    </li>
  {/each}
</ol>
{#if job.status === 'failed' && job.error}
  <p class="err">{job.error}</p>
{/if}

<style>
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
  li { display: flex; gap: 8px; font-size: var(--fs-sm); color: var(--ink-2); }
  li.running { color: var(--ink); }
  li.ok .ico { color: var(--ink-2); }
  li.failed { color: var(--crit); }
  li.pending { color: var(--ink-3); }
  .ico { width: 16px; flex: none; display: flex; justify-content: center; padding-top: 2px; }
  .txt { min-width: 0; flex: 1; }
  pre {
    margin: 3px 0 0; padding: 4px 6px; white-space: pre-wrap; word-break: break-word;
    font: var(--fs-xs)/1.4 var(--mono); color: var(--ink-2); background: var(--bg-inset); border-radius: var(--r-sm);
  }
  .err { margin: 8px 0 0; color: var(--crit); font-size: var(--fs-sm); }
</style>
