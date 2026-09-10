<script lang="ts">
  import { onMount } from 'svelte';
  import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
  import '$lib/theme/tokens.css';
  import '$lib/theme/app.css';
  import '$lib/theme/board.css';
  import '$lib/theme/pages.css';
  import Rail from '$lib/components/Rail.svelte';
  import Topbar from '$lib/components/Topbar.svelte';
  import Toasts from '$lib/components/Toasts.svelte';
  import CmdK from '$lib/components/CmdK.svelte';
  import ConfirmHost from '$lib/components/ConfirmHost.svelte';
  import BottomNav from '$lib/components/BottomNav.svelte';
  import { watchThemeAcrossTabs } from '$lib/stores/theme.svelte';
  import { app } from '$lib/stores/ui.svelte';
  import { startSse } from '$lib/api/sse.svelte';

  let { children } = $props();

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        // Homelab data is poll-based; each query sets its own refetchInterval to match
        // the v1 cadence (30s live tiles, 5min reports…). Background tabs pause.
        staleTime: 15_000,
        retry: 1,
        refetchOnWindowFocus: true,
      },
    },
  });

  onMount(() => {
    const unwatch = watchThemeAcrossTabs();
    const stopSse = startSse(queryClient);
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        app.toggleCmdk();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => { unwatch(); stopSse(); window.removeEventListener('keydown', onKey); };
  });
</script>

<QueryClientProvider client={queryClient}>
  <div class="shell">
    <Rail />
    <div class="main">
      <Topbar />
      <div class="content">
        {@render children()}
      </div>
    </div>
  </div>
  <BottomNav />
  <Toasts />
  <CmdK />
  <ConfirmHost />
</QueryClientProvider>
