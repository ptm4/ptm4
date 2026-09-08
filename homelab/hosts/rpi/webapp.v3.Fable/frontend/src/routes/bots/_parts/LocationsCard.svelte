<script lang="ts">
  // weather: locations — geocode search + list, committed on Save (see WittyCard).
  import { createMutation } from '@tanstack/svelte-query';
  import { MapPin, Search, X } from '@lucide/svelte';
  import { get, ApiError } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import type { GeocodeResult, WeatherLocation } from '$lib/bots';

  let { locations, onChange }: {
    locations: WeatherLocation[];
    onChange: (locations: WeatherLocation[]) => void;
  } = $props();

  function extraErrorMessage(e: unknown, fallback: string): string {
    return (e as ApiError)?.message ?? fallback;
  }

  // Display-name abbreviation for US results, matching the legacy app's habit of
  // "Bellerose, NY" rather than "Bellerose, New York".
  const US_STATES: Record<string, string> = {
    Alabama: 'AL', Alaska: 'AK', Arizona: 'AZ', Arkansas: 'AR', California: 'CA',
    Colorado: 'CO', Connecticut: 'CT', Delaware: 'DE', Florida: 'FL', Georgia: 'GA',
    Hawaii: 'HI', Idaho: 'ID', Illinois: 'IL', Indiana: 'IN', Iowa: 'IA',
    Kansas: 'KS', Kentucky: 'KY', Louisiana: 'LA', Maine: 'ME', Maryland: 'MD',
    Massachusetts: 'MA', Michigan: 'MI', Minnesota: 'MN', Mississippi: 'MS',
    Missouri: 'MO', Montana: 'MT', Nebraska: 'NE', Nevada: 'NV',
    'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY',
    'North Carolina': 'NC', 'North Dakota': 'ND', Ohio: 'OH', Oklahoma: 'OK',
    Oregon: 'OR', Pennsylvania: 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC',
    'South Dakota': 'SD', Tennessee: 'TN', Texas: 'TX', Utah: 'UT', Vermont: 'VT',
    Virginia: 'VA', Washington: 'WA', 'West Virginia': 'WV', Wisconsin: 'WI',
    Wyoming: 'WY', 'District of Columbia': 'DC',
  };

  let q = $state('');
  let results = $state<GeocodeResult[] | null>(null);

  const search = createMutation(() => ({
    mutationFn: (query: string) =>
      get<{ results?: GeocodeResult[] }>(`/api/weather/geocode?q=${encodeURIComponent(query)}`, 20_000),
    onSuccess: (d) => { results = d?.results ?? []; },
    onError: (e: Error) => toast(extraErrorMessage(e, 'Location search failed.'), 'crit'),
  }));

  function add(r: GeocodeResult) {
    q = '';
    results = null;
    if (locations.some((l) => l.lat === r.lat && l.lon === r.lon)) return; // already listed
    const region = r.country === 'US' ? (US_STATES[r.admin1 ?? ''] ?? r.admin1) : r.admin1;
    onChange([...locations, { name: region ? `${r.name}, ${region}` : r.name, lat: r.lat, lon: r.lon }]);
  }
</script>

<section class="card bot-extra">
  <div class="w-head">
    <span class="w-title">Locations ({locations.length})</span>
  </div>
  <div class="bot-list">
    {#each locations as l, i (`${l.name}-${i}`)}
      <div class="bot-list-row">
        <MapPin size={14} aria-hidden="true" /> <span>{l.name}</span>
        <span class="spacer"></span>
        <span class="bot-list-meta mono">{Number(l.lat).toFixed(4)}, {Number(l.lon).toFixed(4)}</span>
        <button class="tbtn sm danger" aria-label="Remove {l.name}"
          onclick={() => onChange(locations.filter((_, j) => j !== i))}><X size={14} aria-hidden="true" /></button>
      </div>
    {/each}
    {#if locations.length === 0}<p class="t-dim">No locations — add one below.</p>{/if}
  </div>
  <div class="bot-add-row">
    <input type="text" bind:value={q} placeholder="city / town name…"
      onkeydown={(e) => { if (e.key === 'Enter' && q.trim()) search.mutate(q.trim()); }} />
    <button class="tbtn" disabled={search.isPending || !q.trim()}
      onclick={() => search.mutate(q.trim())}>
      <Search size={14} aria-hidden="true" /> {search.isPending ? 'Searching…' : 'Search'}
    </button>
  </div>
  {#if results}
    <div class="geo-results">
      {#each results as r, i (i)}
        <button class="tbtn" onclick={() => add(r)}>
          {r.name}{r.admin1 ? `, ${r.admin1}` : ''}
          {' '}<span class="t-dim">({r.country ?? '?'} · {r.lat}, {r.lon})</span>
        </button>
      {/each}
      {#if results.length === 0}<p class="t-dim">No matches.</p>{/if}
    </div>
  {/if}
  <p class="form-note t-dim">Changes here are applied when you hit "Save settings".</p>
</section>
