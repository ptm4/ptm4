<script lang="ts">
  // Renders one widget instance by registry type and provides the widget context
  // (updateOptions) so a widget can persist its own settings without board plumbing.
  import { setContext } from 'svelte';
  import { WIDGET_BY_TYPE } from '$lib/widgets/registry';
  import { WIDGET_CTX, type WidgetContext } from '$lib/widgets/sdk';
  import WidgetError from '$lib/widgets/kit/WidgetError.svelte';
  import type { WidgetInstance } from '$lib/api/types';

  let { widget, onOptionsChange }: {
    widget: WidgetInstance;
    onOptionsChange: (id: string, options: Record<string, unknown>) => void;
  } = $props();

  setContext<WidgetContext>(WIDGET_CTX, {
    get id() { return widget.id; },
    updateOptions: (options) => onOptionsChange(widget.id, { ...(widget.options ?? {}), ...options }),
  });

  let def = $derived(WIDGET_BY_TYPE[widget.type]);
</script>

{#if def}
  {@const Widget = def.component}
  <Widget options={widget.options ?? {}} />
{:else}
  <div class="w-card glass"><WidgetError message={`unknown widget type '${widget.type}'`} /></div>
{/if}
