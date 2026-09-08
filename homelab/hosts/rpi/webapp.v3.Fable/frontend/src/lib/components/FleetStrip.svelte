<script lang="ts">
  // The one-line fleet summary: hosts, containers, pending image updates, open
  // findings, freshness. Everything comes from read-models that are polled anyway.
  import { useVitals, useContainers, useNotifications } from '$lib/api/queries';
  import { HOSTS } from '$lib/nav';
  import { relTime } from '$lib/format';

  const vitals = useVitals();
  const containers = useContainers();
  const notif = useNotifications();

  let hosts = $derived.by(() => {
    const h = vitals.data?.hosts ?? {};
    const names = HOSTS.filter((x) => !x.intermittent).map((x) => x.name);
    const up = names.filter((n) => h[n] && h[n].latest && !h[n].error).length;
    return { up, total: names.length };
  });
  let android = $derived.by(() => {
    const h = vitals.data?.hosts?.android;
    return h && h.latest && !h.error ? 'online' : 'offline';
  });
  let cont = $derived.by(() => {
    const rows = (containers.data?.hosts ?? []).flatMap((x) => x.containers);
    return { up: rows.filter((c) => c.up).length, total: rows.length, updates: rows.filter((c) => c.update_available).length };
  });
  let unacked = $derived(notif.data?.unacked ?? 0);
  let age = $derived.by(() => {
    const h = vitals.data?.hosts ?? {};
    let t = 0;
    for (const x of Object.values(h)) if (x.latest?.t && x.latest.t > t) t = x.latest.t;
    if (!t) return null;
    return relTime(new Date(t < 1e12 ? t * 1000 : t).toISOString());
  });
</script>

<div class="fleet">
  {#if vitals.isError && containers.isError}
    <span class="fitem"><span class="pip" data-s="crit"></span> backend unreachable — {(vitals.error as Error)?.message}</span>
  {:else}
    <a class="fitem" href="/topology">
      <span class="pip" data-s={hosts.up === hosts.total ? 'ok' : hosts.up === 0 ? 'crit' : 'warn'}></span>
      <span class="num">{vitals.data ? `${hosts.up}/${hosts.total}` : '…'}</span> hosts
    </a>
    <a class="fitem" href="/containers">
      <span class="pip" data-s={cont.total === 0 ? 'unknown' : cont.up === cont.total ? 'ok' : 'warn'}></span>
      <span class="num">{containers.data ? `${cont.up}/${cont.total}` : '…'}</span> containers
    </a>
    <a class="fitem" href="/updates">
      <span class="pip" data-s={cont.updates > 0 ? 'warn' : 'ok'}></span>
      <span class="num">{containers.data ? cont.updates : '…'}</span> image updates
    </a>
    <a class="fitem" href="/incidents">
      <span class="pip" data-s={unacked > 0 ? (unacked > 5 ? 'crit' : 'warn') : 'ok'}></span>
      <span class="num">{notif.data ? unacked : '…'}</span> open findings
    </a>
    <a class="fitem" href="/host/android">
      <span class="pip" data-s={android === 'online' ? 'ok' : 'unknown'}></span>
      <span class="num">android</span> {android}{#if android === 'offline'} · by design{/if}
    </a>
    <span class="age">{age ? `vitals ${age}` : vitals.isLoading ? 'loading…' : 'no vitals'}</span>
  {/if}
</div>
