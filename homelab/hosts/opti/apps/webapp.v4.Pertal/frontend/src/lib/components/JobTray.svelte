<script lang="ts">
  // Bottom-right tray (bottom sheet on phones) with the jobs this browser started and
  // any action that failed to start. It is how a button press stays visible until it
  // has either finished or said exactly why not.
  import { X, ChevronDown, ChevronUp } from '@lucide/svelte';
  import JobSteps from './JobSteps.svelte';
  import { actions } from '$lib/actions.svelte';
  import { live } from '$lib/live.svelte';
  import { ago } from '$lib/format';

  const jobs = $derived(actions.mine.map((id) => live.jobs.find((j) => j.id === id)).filter((j) => !!j));
  const running = $derived(jobs.filter((j) => j.status === 'running').length);
  const visible = $derived(jobs.length > 0 || actions.errors.length > 0);
</script>

{#if visible}
  <aside class="tray" class:open={actions.trayOpen} aria-label="Actions">
    <button class="head" onclick={() => (actions.trayOpen = !actions.trayOpen)}>
      <span class="title">
        Actions
        {#if running}<span class="badge accent">{running} running</span>{/if}
        {#if actions.errors.length}<span class="badge crit">{actions.errors.length} failed to start</span>{/if}
      </span>
      {#if actions.trayOpen}<ChevronDown size={16} />{:else}<ChevronUp size={16} />{/if}
    </button>
    {#if actions.trayOpen}
      <div class="list">
        {#each actions.errors as e (e.id)}
          <div class="item">
            <div class="item-head">
              <span class="badge crit">not started</span><strong>{e.title}</strong>
              <button class="btn ghost icon" aria-label="Dismiss" onclick={() => actions.dismissError(e.id)}><X size={14} /></button>
            </div>
            <p class="err">{e.text}</p>
          </div>
        {/each}
        {#each jobs as j (j.id)}
          <div class="item">
            <div class="item-head">
              <span class="badge {j.status === 'failed' ? 'crit' : j.status === 'running' ? 'accent' : ''}">{j.status}</span>
              <a href="/r/{j.resource}">{j.title}</a>
              <span class="faint">{ago(j.started_at, live.now)}</span>
            </div>
            <JobSteps job={j} />
          </div>
        {/each}
      </div>
    {/if}
  </aside>
{/if}

<style>
  .tray {
    position: fixed; right: 16px; bottom: 16px; z-index: 40;
    width: 380px; max-height: min(70vh, 560px);
    display: flex; flex-direction: column;
    background: var(--surface); border: 1px solid var(--border-2); border-radius: var(--r-lg);
    box-shadow: var(--shadow);
  }
  .head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 10px 14px; border: 0; background: transparent; cursor: pointer; text-align: left;
  }
  .title { display: flex; align-items: center; gap: 8px; font-weight: 600; }
  .list { overflow: auto; border-top: 1px solid var(--border); }
  .item { padding: 10px 14px; border-bottom: 1px solid var(--border); }
  .item:last-child { border-bottom: 0; }
  .item-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; font-size: var(--fs-sm); }
  .item-head a, .item-head strong { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { margin: 0; color: var(--crit); font-size: var(--fs-sm); }
  @media (max-width: 720px) {
    .tray { left: 8px; right: 8px; bottom: 8px; width: auto; }
  }
</style>
