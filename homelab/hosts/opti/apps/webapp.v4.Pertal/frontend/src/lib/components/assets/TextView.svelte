<script lang="ts">
  // A text file from the library: the first 256 KB, JSON pretty-printed when it is whole.
  import type { AssetFile } from '$lib/api';
  import { bytes } from '$lib/format';
  import { ext, fileUrl } from '$lib/assets';

  let { rel, file }: { rel: string; file: AssetFile } = $props();
  const MAX = 256 * 1024;
  let text = $state<string | null>(null);
  let err = $state<string | null>(null);
  const cut = $derived(file.size > MAX);

  $effect(() => {
    const url = fileUrl(rel, file.mtime);
    const whole = file.size <= MAX;
    const json = ext(file.name) === 'json';
    text = null;
    err = null;
    const ac = new AbortController();
    fetch(url, { headers: whole ? {} : { Range: `bytes=0-${MAX - 1}` }, signal: ac.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`ptm answered HTTP ${r.status}`);
        let t = await r.text();
        if (whole && json) {
          try { t = JSON.stringify(JSON.parse(t), null, 2); } catch { /* not valid JSON: show it as it is */ }
        }
        text = t;
      })
      .catch((e) => { if (!ac.signal.aborted) err = (e as Error).message; });
    return () => ac.abort();
  });
</script>

{#if err}
  <p class="panel empty">Could not read this file: {err}</p>
{:else if text === null}
  <p class="panel empty">Reading from ptm…</p>
{:else}
  {#if cut}<p class="faint note">Showing the first {bytes(MAX)} of {bytes(file.size)}. Download it for the rest.</p>{/if}
  <pre class="text">{text || '(empty file)'}</pre>
{/if}

<style>
  .note { margin: 0 0 var(--s2); font-size: var(--fs-sm); }
  .text {
    margin: 0; max-height: min(76vh, 860px); overflow: auto; padding: var(--s3) var(--s4);
    border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--bg-inset);
    font: var(--fs-sm)/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; color: var(--ink);
  }
</style>
