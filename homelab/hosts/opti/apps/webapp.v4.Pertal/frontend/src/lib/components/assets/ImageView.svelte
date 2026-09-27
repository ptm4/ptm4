<script lang="ts">
  // One image from the library, as large as the page allows; click for actual size.
  // Formats a browser can't draw (TGA, TIFF) come through ptm's 2048 px thumbnail.
  import type { AssetFile } from '$lib/api';
  import { browserCanShow, fileUrl, thumbUrl } from '$lib/assets';

  let { rel, file }: { rel: string; file: AssetFile } = $props();
  let actual = $state(false);
  let dims = $state<string | null>(null);
  let failed = $state(false);
  const native = $derived(browserCanShow(file.name));
  const src = $derived(native ? fileUrl(rel, file.mtime) : thumbUrl(rel, 2048, file.mtime));
  $effect(() => { void src; actual = false; dims = null; failed = false; });
</script>

<div class="stage" class:actual>
  {#if failed}
    <p class="faint">This image could not be loaded from ptm.</p>
  {:else}
    <button class="img" onclick={() => (actual = !actual)} title={actual ? 'Fit to the page' : 'Show at actual size'}>
      <img {src} alt={file.name}
        onload={(e) => { const i = e.currentTarget as HTMLImageElement; dims = `${i.naturalWidth} × ${i.naturalHeight}`; }}
        onerror={() => (failed = true)} />
    </button>
  {/if}
  {#if dims}<span class="dims">{dims}{native ? '' : ' · preview'}</span>{/if}
</div>

<style>
  .stage {
    position: relative; height: min(76vh, 860px); min-height: 320px; overflow: hidden;
    display: flex; align-items: center; justify-content: center;
    border: 1px solid var(--border); border-radius: var(--r-lg); background: var(--bg-inset);
  }
  .stage.actual { overflow: auto; display: block; }
  .img { border: 0; padding: 0; background: none; cursor: zoom-in; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; }
  .img img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .actual .img { cursor: zoom-out; width: max-content; height: auto; display: block; }
  .actual .img img { max-width: none; max-height: none; }
  .dims {
    position: absolute; right: 10px; bottom: 10px; padding: 2px 8px; border-radius: var(--r-sm);
    background: var(--surface); color: var(--ink-2); font-size: var(--fs-xs); font-family: var(--mono);
  }
  .actual .dims { position: sticky; float: right; margin: -30px 10px 10px 0; }
  @media (max-width: 900px) { .stage { height: 62vh; } }
</style>
