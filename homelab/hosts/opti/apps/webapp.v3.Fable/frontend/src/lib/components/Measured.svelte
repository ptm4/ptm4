<script lang="ts">
  // "Measured 4 min ago" — the age of a number, next to the number.
  //
  // WHY THIS EXISTS. Peter, 2026-09-10: "Does this site read live & if it does why do
  // we need the sync? It feels unreliable at times."
  //
  // The site is half live and half snapshot. Vitals stream every 30s; package counts,
  // disks, ports and container inventory come from collectors that SSH the whole fleet
  // and therefore run on a schedule. That split is a reasonable engineering answer —
  // you cannot run smartctl across four hosts on every page load. What was NOT
  // reasonable is that both kinds rendered identically, so a number measured ten
  // seconds ago and one measured five days ago looked exactly the same. The data was
  // never lying; the page was, by omission. That is what "unreliable" meant.
  //
  // So: anything derived from a collector says when it was taken. Fresh is quiet —
  // nearly invisible — because a current number needs no defending. Age only becomes
  // loud once it is old enough to change a decision you might make from it.
  import { relTime } from '$lib/format';

  let {
    at,
    /** What produced it, shown on hover — "homelab-doctor", "software-inventory". */
    source = null,
    /** Minutes past which this stops being quiet. Defaults to a doctor cycle + slack. */
    warnAfterMin = 45,
    /** Minutes past which it is loud. */
    staleAfterMin = 24 * 60,
    /** `bare` drops the word "measured" for tight spots like a tile footer. */
    bare = false,
  }: {
    at: string | null | undefined;
    source?: string | null;
    warnAfterMin?: number;
    staleAfterMin?: number;
    bare?: boolean;
  } = $props();

  // Recomputed on a timer so an open tab does not keep claiming "just now" for an hour.
  let now = $state(Date.now());
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 30_000);
    return () => clearInterval(t);
  });

  let ms = $derived(at ? now - Date.parse(at) : null);
  let tone = $derived(
    ms == null ? 'unknown'
    : ms > staleAfterMin * 60_000 ? 'stale'
    : ms > warnAfterMin * 60_000 ? 'aging'
    : 'fresh',
  );

  let title = $derived(
    at
      ? `Measured ${new Date(at).toLocaleString()}${source ? ` by ${source}` : ''}.\n`
        + 'This figure is collected on a schedule, not read live. Use Refresh to re-measure now.'
      : 'No measurement time reported for this figure.',
  );
</script>

<span class="measured" data-t={tone} {title}>
  {#if ms == null}
    {bare ? 'age unknown' : 'measurement time unknown'}
  {:else}
    {bare ? '' : 'measured '}{relTime(at!)}
  {/if}
</span>

<style>
  .measured {
    font-size: var(--fs-xs);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
    color: var(--ink-3);
  }
  /* Fresh is deliberately the quietest thing on the row. A current number is the
     expected case and should not compete with the number itself for attention. */
  .measured[data-t="fresh"] { opacity: .65; }
  .measured[data-t="aging"] { color: var(--warn); opacity: 1; }
  .measured[data-t="stale"] { color: var(--crit); opacity: 1; font-weight: 600; }
  .measured[data-t="unknown"] { color: var(--crit); opacity: 1; }
</style>
