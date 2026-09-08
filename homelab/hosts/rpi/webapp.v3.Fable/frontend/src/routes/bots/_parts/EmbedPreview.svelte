<script lang="ts">
  // Discord-style embed rendering. **bold** is the only markdown Discord embeds use
  // in these payloads; everything else is plain text.
  import type { BotPreview } from '$lib/bots';

  let { preview }: { preview: BotPreview } = $props();

  function mdParts(s: string): { bold: boolean; text: string }[] {
    return s.split(/(\*\*[^*]+\*\*)/g).map((part) =>
      part.startsWith('**') && part.endsWith('**')
        ? { bold: true, text: part.slice(2, -2) }
        : { bold: false, text: part });
  }

  let embed = $derived(preview.payload?.embeds?.[0] ?? {});
  let fields = $derived((embed.fields ?? []).filter((f) => (f.name || '').replace(/[​\s]/g, '') !== ''));
</script>

{#snippet mdText(s: string)}
  {#each mdParts(s) as p, i (i)}
    {#if p.bold}<strong>{p.text}</strong>{:else}<span>{p.text}</span>{/if}
  {/each}
{/snippet}

{#if preview.payload?.content}
  <div class="msg-content">{@render mdText(preview.payload.content)}</div>
{/if}
<div class="embed-preview">
  {#if preview.payload?.username}<div class="embed-author">{preview.payload.username}</div>{/if}
  {#if embed.title}<div class="embed-title">{embed.title}</div>{/if}
  {#if embed.description}<div class="embed-desc">{@render mdText(embed.description)}</div>{/if}
  <div class="embed-fields">
    {#each fields as f, i (i)}
      <div class="embed-field{f.inline ? ' inline' : ''}">
        <div class="embed-field-name">{f.name}</div>
        <div class="embed-field-value">{@render mdText(f.value)}</div>
      </div>
    {/each}
  </div>
  {#if embed.footer}<div class="embed-footer">{embed.footer.text}</div>{/if}
</div>
{#if preview.failed && preview.failed.length > 0}
  <div class="t-crit">No data for: {preview.failed.join(', ')}</div>
{/if}
