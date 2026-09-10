<script lang="ts">
  // Home — the couch/phone view.
  //
  // WHAT THIS PAGE IS FOR (Peter's answer, 2026-09-10, after fairly pointing out that
  // Home and Launchpad had become the same page): this is what you open on your phone
  // from the sofa. It answers two questions and then gets out of the way —
  //
  //     1. Is anything wrong?        (and if not, say so and stop talking)
  //     2. What do I want to open?   (media, streams, the handful of things you use)
  //
  // WHAT IT IS NOT, and why the old version was wrong: it used to be a portal made of
  // other pages — the topology map, the activity feed, the launch dock, a streams card,
  // a fleet strip of numbers. Everything on it already had a better home one click away,
  // which is exactly why it ended up indistinguishable from Launchpad. A homepage that
  // is a directory of the other pages is not a homepage.
  //
  // So the design rules here are subtractive:
  //   - The verdict comes first, in a full sentence, readable at arm's length.
  //   - Healthy renders as ABSENCE. Nothing that is fine gets a card, a colour or a
  //     number. If everything is fine the page is nearly empty, and that emptiness is
  //     the information.
  //   - Numbers only where a number is the point. "3/3 hosts up" is for the Monitor.
  //   - Touch targets are big. This is a phone in one hand.
  //   - No live-updating counters to watch. If you want to watch something, that is
  //     the Monitor, and it says so.
  import { ArrowRight, Tv, Radio, Rocket, Gauge } from '@lucide/svelte';
  import { useIncidents } from '$lib/api/incidents';
  import { useHosts } from '$lib/api/fleet';
  import { useVitals } from '$lib/api/queries';
  import StreamsCard from '$lib/features/streams/StreamsCard.svelte';
  import { ALL_LINKS, iconUrl, isExternal } from '$lib/links';
  import { relTime } from '$lib/format';

  const incidents = useIncidents();
  const hosts = useHosts();
  const vitals = useVitals();

  let open = $derived((incidents.data?.incidents ?? []).filter((i) => i.status === 'open'));
  let crit = $derived(open.filter((i) => i.severity === 'crit'));

  // A host counts as down only if it is a real server that should be up. android is a
  // phone and documented intermittent; calling it "down" every night trains you to
  // ignore this line, which would defeat the entire page.
  let down = $derived(
    (hosts.data?.hosts ?? []).filter(
      (h) => !h.intermittent && h.agent && !vitals.data?.hosts?.[h.name]?.latest,
    ),
  );

  // The newest sample across the fleet, so the footer can say how fresh this verdict
  // is. There is no single "checked_at" on the rollup — each host carries its own, as
  // a `t` epoch — and claiming a freshness the data does not have is the exact failure
  // mode this redesign is against.
  let lastSeen = $derived.by(() => {
    const ts = Object.values(vitals.data?.hosts ?? {})
      .map((h) => h.latest?.t)
      .filter((t): t is number => typeof t === 'number');
    return ts.length ? new Date(Math.max(...ts) * 1000).toISOString() : null;
  });

  // The whole page in one sentence. Ordered by what would actually ruin your evening.
  let verdict = $derived.by(() => {
    if (incidents.isPending || hosts.isPending) return { tone: 'idle', line: 'Checking…', sub: '' };
    if (down.length) {
      return {
        tone: 'crit',
        line: down.length === 1 ? `${down[0].label} is not answering.` : `${down.length} hosts are not answering.`,
        sub: down.map((h) => `${h.label} — ${h.role}`).join(' · '),
      };
    }
    if (crit.length) {
      return { tone: 'crit', line: crit[0].title, sub: crit.length > 1 ? `and ${crit.length - 1} more needing attention` : '' };
    }
    if (open.length) {
      return {
        tone: 'warn',
        line: open.length === 1 ? open[0].title : `${open.length} things want a look.`,
        sub: open.length === 1 ? (open[0].host ?? '') : open.slice(0, 3).map((i) => i.title).join(' · '),
      };
    }
    return { tone: 'ok', line: 'Everything’s fine.', sub: 'Nothing is asking for you.' };
  });

  // The couch shortlist. Deliberately short and hand-picked rather than the full
  // Launchpad — this is "the things I actually reach for from the sofa", and the
  // Launchpad is one tap away for everything else. Matched by label against the same
  // catalogue the Launchpad uses, so a URL only ever has to be right in one place;
  // a rename there drops the tile rather than shipping a dead link.
  const COUCH_LABELS = ['Jellyfin', 'Kavita (comics)', 'Vaultwarden', 'Notes'];
  let couch = $derived(
    COUCH_LABELS.map((label) => ALL_LINKS.find((l) => l.label === label)).filter((l) => !!l),
  );
</script>

<div class="couch">
  <!-- ── The verdict ──────────────────────────────────────────────────────── -->
  <section class="verdict" data-t={verdict.tone}>
    <p class="line">{verdict.line}</p>
    {#if verdict.sub}<p class="sub">{verdict.sub}</p>{/if}
    {#if open.length || down.length}
      <a class="act" href="/feed?view=incidents">Look at it <ArrowRight size={14} aria-hidden="true" /></a>
    {/if}
  </section>

  <!-- ── What's on ────────────────────────────────────────────────────────── -->
  <section class="block">
    <h2><Radio size={15} aria-hidden="true" /> What’s on</h2>
    <StreamsCard />
  </section>

  <!-- ── Open something ───────────────────────────────────────────────────── -->
  <section class="block">
    <h2><Tv size={15} aria-hidden="true" /> Open something</h2>
    <div class="tiles">
      {#each couch as l (l.label)}
        <a class="tile" href={l.url}
           target={isExternal(l.url) ? '_blank' : undefined}
           rel={isExternal(l.url) ? 'noreferrer' : undefined}>
          <span class="t"><img src={iconUrl(l.icon)} alt="" width="16" height="16" />{l.label}</span>
          <span class="d">{l.group}</span>
        </a>
      {/each}
      <a class="tile ghost" href="/launchpad">
        <span class="t"><Rocket size={14} aria-hidden="true" /> Everything else</span>
        <span class="d">the full Launchpad</span>
      </a>
    </div>
  </section>

  <!-- The one honest pointer out. Home does not try to be the Monitor. -->
  <footer>
    <a href="/monitor"><Gauge size={13} aria-hidden="true" /> Watch it live on the Monitor</a>
    {#if lastSeen}<span class="ts">fleet seen {relTime(lastSeen)}</span>{/if}
  </footer>
</div>

<style>
  .couch { max-width: 720px; margin: 0 auto; display: flex; flex-direction: column; gap: var(--s6); }

  /* The verdict. Big enough to read from across a room; quiet when there is nothing
     to say. `ok` gets no colour at all — that is the point. */
  .verdict { padding: var(--s5) 0 var(--s4); border-bottom: 1px solid var(--border); }
  .line { margin: 0; font-size: var(--fs-2xl); line-height: 1.25; font-weight: 600;
          letter-spacing: -0.01em; color: var(--ink); }
  .sub { margin: var(--s3) 0 0; font-size: var(--fs-md); color: var(--ink-2); line-height: 1.5; }
  .verdict[data-t="ok"] .sub { color: var(--ink-3); }
  .verdict[data-t="warn"] .line { color: var(--warn); }
  .verdict[data-t="crit"] .line { color: var(--crit); }
  .verdict[data-t="idle"] .line { color: var(--ink-3); font-weight: 400; }
  .act { display: inline-flex; align-items: center; gap: 6px; margin-top: var(--s4);
         padding: var(--s2) var(--s4); border-radius: var(--r);
         background: var(--surface-2); border: 1px solid var(--border-2);
         color: var(--ink); font-size: var(--fs-sm); font-weight: 500; }
  .act:hover { border-color: var(--accent-muted); color: var(--accent); }

  .block h2 { display: flex; align-items: center; gap: var(--s2);
              font-size: var(--fs-sm); font-weight: 600; text-transform: uppercase;
              letter-spacing: .08em; color: var(--ink-3); margin: 0 0 var(--s3); }

  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: var(--s3); }
  .tile { display: flex; flex-direction: column; gap: 2px; min-height: 76px;
          justify-content: center; padding: var(--s4);
          background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--r); color: var(--ink); }
  .tile:hover { border-color: var(--accent-muted); }
  .tile .t { display: flex; align-items: center; gap: 6px; font-size: var(--fs-md); font-weight: 500; }
  .tile .d { font-size: var(--fs-xs); color: var(--ink-3); }
  .tile.ghost { background: none; border-style: dashed; }

  footer { display: flex; align-items: center; gap: var(--s4); flex-wrap: wrap;
           padding-top: var(--s4); border-top: 1px solid var(--border);
           font-size: var(--fs-xs); color: var(--ink-3); }
  footer a { display: inline-flex; align-items: center; gap: 5px; color: var(--ink-3); }
  footer a:hover { color: var(--accent); }
  .ts { margin-left: auto; }

  @media (max-width: 620px) {
    .line { font-size: var(--fs-xl); }
    .couch { gap: var(--s5); }
    /* Phone: two big targets per row, thumb-sized. */
    .tiles { grid-template-columns: 1fr 1fr; }
    .tile { min-height: 84px; }
  }
</style>
