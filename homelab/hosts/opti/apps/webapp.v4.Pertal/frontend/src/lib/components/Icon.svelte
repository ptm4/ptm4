<script lang="ts">
  // Backend action definitions name icons by lucide slug; this maps them to components.
  import {
    RefreshCw, RotateCcw, Download, FolderSync, Pause, Play, Power, Server, Container, Bot,
    Boxes, Smartphone, ExternalLink, Activity, Settings, Gauge, Network, ScrollText, Inbox,
    Radio, Rocket, FileChartColumn, Search, Library, Circle,
  } from '@lucide/svelte';

  let { name, size = 15 }: { name: string; size?: number } = $props();

  const map: Record<string, any> = {
    'refresh-cw': RefreshCw, 'rotate-ccw': RotateCcw, download: Download, 'folder-sync': FolderSync,
    pause: Pause, play: Play, power: Power, server: Server, container: Container, bot: Bot,
    boxes: Boxes, smartphone: Smartphone, 'external-link': ExternalLink, activity: Activity,
    settings: Settings, gauge: Gauge, network: Network, 'scroll-text': ScrollText, inbox: Inbox,
    radio: Radio, rocket: Rocket, 'file-chart-column': FileChartColumn, search: Search, library: Library,
  };
  const Cmp = $derived(map[name] ?? Circle);
</script>

<Cmp {size} strokeWidth={1.75} aria-hidden="true" />
