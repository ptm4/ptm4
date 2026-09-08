<script lang="ts">
  // Per-widget options form, generated from the registry's option definitions —
  // no per-widget form code exists anywhere in the app.
  import Modal from '$lib/components/Modal.svelte';
  import { WIDGET_BY_TYPE } from '$lib/widgets/registry';
  import type { WidgetInstance } from '$lib/api/types';

  let { widget, onClose, onChange }: {
    widget: WidgetInstance | null;
    onClose: () => void;
    onChange: (id: string, options: Record<string, unknown>) => void;
  } = $props();

  let def = $derived(widget ? WIDGET_BY_TYPE[widget.type] : undefined);
  let options = $derived(widget?.options ?? {});

  const set = (key: string, value: unknown) => { if (widget) onChange(widget.id, { ...options, [key]: value }); };
  const str = (v: unknown, fb = '') => (v == null ? fb : String(v));
</script>

{#if widget}
  <Modal open title="{def?.label ?? widget.type} settings" onclose={onClose}>
    {#if !def?.options?.length}
      <p class="dim">This widget has no options.</p>
    {/if}
    <div class="form-rows">
      {#each def?.options ?? [] as o (o.key)}
        <label class="form-row">
          <span>{o.label}</span>
          {#if o.type === 'select'}
            <select value={str(options[o.key] ?? o.default ?? o.choices?.[0]?.value)} onchange={(e) => set(o.key, e.currentTarget.value)}>
              {#each o.choices ?? [] as c (c.value)}<option value={c.value}>{c.label}</option>{/each}
            </select>
          {:else if o.type === 'number'}
            <input type="number" min={o.min} max={o.max} value={Number(options[o.key] ?? o.default ?? o.min ?? 0)}
              onchange={(e) => set(o.key, Number(e.currentTarget.value))} />
          {:else if o.type === 'boolean'}
            <input type="checkbox" checked={options[o.key] == null ? (o.default as boolean ?? true) : options[o.key] !== false}
              onchange={(e) => set(o.key, e.currentTarget.checked)} />
          {:else}
            <input type="text" value={str(options[o.key] ?? o.default)} onchange={(e) => set(o.key, e.currentTarget.value)} />
          {/if}
        </label>
      {/each}
    </div>
  </Modal>
{/if}
