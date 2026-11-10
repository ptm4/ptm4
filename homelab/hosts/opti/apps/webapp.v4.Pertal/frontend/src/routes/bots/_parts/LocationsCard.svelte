<script lang="ts">
  // Weather bot: locations. Geocode search plus a list, committed on "Save settings".
  import { MapPin, Search, X } from '@lucide/svelte';
  import { botCall, BOT_BY_ID, botError, type GeocodeResult, type WeatherLocation } from '$lib/bots';

  let { locations, onChange }: { locations: WeatherLocation[]; onChange: (l: WeatherLocation[]) => void } = $props();

  // "Bellerose, NY" rather than "Bellerose, New York", as the bot has always shown it.
  const US_STATES: Record<string, string> = {
    Alabama: 'AL', Alaska: 'AK', Arizona: 'AZ', Arkansas: 'AR', California: 'CA', Colorado: 'CO', Connecticut: 'CT',
    Delaware: 'DE', Florida: 'FL', Georgia: 'GA', Hawaii: 'HI', Idaho: 'ID', Illinois: 'IL', Indiana: 'IN', Iowa: 'IA',
    Kansas: 'KS', Kentucky: 'KY', Louisiana: 'LA', Maine: 'ME', Maryland: 'MD', Massachusetts: 'MA', Michigan: 'MI',
    Minnesota: 'MN', Mississippi: 'MS', Missouri: 'MO', Montana: 'MT', Nebraska: 'NE', Nevada: 'NV', 'New Hampshire': 'NH',
    'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', Ohio: 'OH',
    Oklahoma: 'OK', Oregon: 'OR', Pennsylvania: 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD',
    Tennessee: 'TN', Texas: 'TX', Utah: 'UT', Vermont: 'VT', Virginia: 'VA', Washington: 'WA', 'West Virginia': 'WV',
    Wisconsin: 'WI', Wyoming: 'WY', 'District of Columbia': 'DC',
  };

  let q = $state('');
  let results = $state<GeocodeResult[] | null>(null);
  let searching = $state(false);
  let err = $state<string | null>(null);

  async function search() {
    const query = q.trim();
    if (!query) return;
    searching = true; err = null;
    try { results = (await botCall<{ results?: GeocodeResult[] }>(`/api/weather/geocode?q=${encodeURIComponent(query)}`, { timeoutMs: 20_000 }))?.results ?? []; }
    catch (e) { err = botError(BOT_BY_ID.weather, e); } finally { searching = false; }
  }
  function add(r: GeocodeResult) {
    q = ''; results = null;
    if (locations.some((l) => l.lat === r.lat && l.lon === r.lon)) return;
    const region = r.country === 'US' ? (US_STATES[r.admin1 ?? ''] ?? r.admin1) : r.admin1;
    onChange([...locations, { name: region ? `${r.name}, ${region}` : r.name, lat: r.lat, lon: r.lon }]);
  }
</script>

<section class="panel">
  <div class="panel-head"><h2>Locations ({locations.length})</h2></div>
  <div class="panel-body body">
    <div class="rows list">
      {#each locations as l, i (`${l.name}-${i}`)}
        <div class="row item"><MapPin size={14} /><span>{l.name}</span><span class="mono faint">{Number(l.lat).toFixed(4)}, {Number(l.lon).toFixed(4)}</span>
          <button class="btn icon ghost" aria-label="Remove {l.name}" onclick={() => onChange(locations.filter((_, j) => j !== i))}><X size={14} /></button></div>
      {:else}
        <p class="faint">No locations. Add one below.</p>
      {/each}
    </div>
    <div class="add">
      <input class="field" type="text" bind:value={q} placeholder="city or town" onkeydown={(e) => { if (e.key === 'Enter') void search(); }} />
      <button class="btn" disabled={searching || !q.trim()} onclick={search}><Search size={14} /> {searching ? 'Searching…' : 'Search'}</button>
    </div>
    {#if err}<p class="crit">{err}</p>{/if}
    {#if results}
      <div class="results">
        {#each results as r, i (i)}
          <button class="btn" onclick={() => add(r)}>{r.name}{r.admin1 ? `, ${r.admin1}` : ''} <span class="faint">({r.country ?? '?'} · {r.lat}, {r.lon})</span></button>
        {:else}
          <p class="faint">No matches.</p>
        {/each}
      </div>
    {/if}
    <small class="faint">Changes here apply when you press "Save settings".</small>
  </div>
</section>

<style>
  .body { display: flex; flex-direction: column; gap: var(--s3); }
  .list { border: 1px solid var(--border); border-radius: var(--r); }
  .item { grid-template-columns: auto 1fr auto auto; padding: 4px var(--s3); font-size: var(--fs-sm); }
  .list p { margin: 0; padding: 6px var(--s3); }
  .add { display: flex; gap: 8px; }
  .add input { flex: 1; min-width: 0; }
  .results { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
  .crit { color: var(--crit); margin: 0; }
</style>
