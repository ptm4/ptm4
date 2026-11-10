<script lang="ts">
  // Discord-style embed rendering. **bold** is the only markdown these payloads use.
  import type { BotPreview } from '$lib/bots';

  let { preview }: { preview: BotPreview } = $props();

  const mdParts = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((p) =>
    p.startsWith('**') && p.endsWith('**') ? { bold: true, text: p.slice(2, -2) } : { bold: false, text: p });
  const embed = $derived(preview.payload?.embeds?.[0] ?? {});
  const fields = $derived((embed.fields ?? []).filter((f) => (f.name || '').replace(/[​\s]/g, '') !== ''));
</script>

{#snippet md(s: string)}{#each mdParts(s) as p, i (i)}{#if p.bold}<strong>{p.text}</strong>{:else}<span>{p.text}</span>{/if}{/each}{/snippet}

{#if preview.payload?.content}<div class="content">{@render md(preview.payload.content)}</div>{/if}
<div class="embed">
  {#if preview.payload?.username}<div class="author">{preview.payload.username}</div>{/if}
  {#if embed.title}<div class="title">{embed.title}</div>{/if}
  {#if embed.description}<div class="desc">{@render md(embed.description)}</div>{/if}
  <div class="fields">
    {#each fields as f, i (i)}
      <div class="field" class:inline={f.inline}><div class="fname">{f.name}</div><div>{@render md(f.value)}</div></div>
    {/each}
  </div>
  {#if embed.footer}<div class="footer faint">{embed.footer.text}</div>{/if}
</div>
{#if preview.failed?.length}<p class="crit">No data for: {preview.failed.join(', ')}</p>{/if}

<style>
  .content { white-space: pre-wrap; margin-bottom: var(--s2); font-size: var(--fs-sm); }
  .embed { border-left: 4px solid var(--accent); background: var(--surface-2); border-radius: var(--r); padding: var(--s3); font-size: var(--fs-sm); display: flex; flex-direction: column; gap: 6px; max-width: 520px; }
  .author { font-size: var(--fs-xs); font-weight: 600; }
  .title { font-weight: 600; }
  .desc { white-space: pre-wrap; }
  .fields { display: flex; flex-wrap: wrap; gap: 8px; }
  .field { flex: 1 1 100%; white-space: pre-wrap; }
  .field.inline { flex: 1 1 30%; }
  .fname { font-weight: 600; }
  .footer { font-size: var(--fs-xs); }
  .crit { color: var(--crit); }
</style>
