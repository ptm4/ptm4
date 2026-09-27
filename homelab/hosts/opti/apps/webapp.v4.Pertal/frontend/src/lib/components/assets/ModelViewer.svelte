<script lang="ts" module>
  // One inventory per library root (e.g. DND5E/catalog/EXPORTED_INVENTORY.json), fetched
  // once per page load and shared by every model opened.
  const inventories = new Map<string, Promise<any>>();
  function inventory(root: string, url: string) {
    if (!inventories.has(root)) {
      inventories.set(root, fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null));
    }
    return inventories.get(root)!;
  }
</script>

<script lang="ts">
  // The library's 3D inspector (E:\Assets\DND5E\viewer.html), inside the page: the same
  // model-viewer build (byte-identical to the library's vendor copy), the same backdrop,
  // light and tone mapping, and the same controls — Front / Side / Back / Rotate, face
  // close-up, LODs, exposure, rig animations. For a DND5E asset it reads the item's
  // audit/BUILD.json and the library inventory, as viewer.html does; any other .glb gets
  // the same stage with the controls that apply.
  import { onMount, untrack } from 'svelte';
  import { api, type AssetFile } from '$lib/api';
  import { fileUrl, join, parentOf, baseName } from '$lib/assets';
  import { bytes } from '$lib/format';

  interface ModelViewerEl extends HTMLElement {
    cameraOrbit: string; cameraTarget: string; autoRotate: boolean; exposure: number;
    availableAnimations: string[]; animationName: string | undefined;
    currentTime: number; duration: number; paused: boolean; loaded: boolean; play(): void; pause(): void;
  }

  let { rel, file, siblings }: { rel: string; file: AssetFile; siblings: AssetFile[] } = $props();

  // DND5E layout: <item>/models/<stem>.glb, <item>/lods/<stem>_LOD1.glb, <item>/audit/BUILD.json
  const dir = $derived(parentOf(rel));
  const dirName = $derived(baseName(dir).toLowerCase());
  const itemDir = $derived(dirName === 'models' || dirName === 'lods' ? parentOf(dir) : dir);
  const root = $derived(rel.split('/')[0]);
  const itemId = $derived(itemDir.startsWith(`${root}/`) ? itemDir.slice(root.length + 1) : itemDir);
  const stem = $derived(file.name.replace(/\.[^.]+$/, '').replace(/_LOD\d+$/i, ''));
  const clickedLevel = $derived(file.name.match(/_LOD(\d+)\.[^.]+$/i)?.[1] ?? '0');

  type Ctx = { audit: any; item: any; sources: Map<string, string>; downloads: { label: string; href: string; size: number }[] };
  let ctx = $state.raw<Ctx>({ audit: null, item: null, sources: new Map(), downloads: [] });

  let el = $state<HTMLElement>();
  const mv = $derived(el as ModelViewerEl | undefined);
  let engine = $state<'loading' | 'ready' | 'failed'>('loading');
  let status = $state('Loading from ptm…');
  let level = $state('0');
  let exposure = $state(1);
  let spinning = $state(false);
  let faceMode = $state(false);
  let clips = $state<string[]>([]);
  let clip = $state('');
  let playing = $state(false);
  let time = $state(0);
  let duration = $state(1);

  onMount(() => {
    import('@google/model-viewer/dist/model-viewer.min.js')
      .then(() => (engine = 'ready'))
      .catch((e) => { engine = 'failed'; status = `The 3D viewer could not start: ${e.message}`; });
  });

  // A new file: reset the controls, then gather what the library knows about it.
  $effect(() => {
    const target = rel;
    untrack(() => {
      level = clickedLevel;
      faceMode = spinning = playing = false;
      clips = []; clip = ''; time = 0; duration = 1;
      status = 'Loading from ptm…';
      ctx = { audit: null, item: null, sources: new Map([[clickedLevel, fileUrl(rel, file.mtime)]]), downloads: [] };
      void gather(target);
    });
  });

  async function gather(target: string) {
    const inModels = dirName === 'models', inLods = dirName === 'lods';
    const [audit, inv, models, lods] = await Promise.all([
      fetch(fileUrl(`${itemDir}/audit/BUILD.json`)).then((r) => (r.ok ? r.json() : null)).catch(() => null),
      inventory(root, fileUrl(`${root}/catalog/EXPORTED_INVENTORY.json`)),
      inModels ? { files: siblings } : inLods ? api.assets.list(`${itemDir}/models`).catch(() => null) : { files: siblings },
      inLods ? { files: siblings } : inModels ? api.assets.list(`${itemDir}/lods`).catch(() => null) : null,
    ]);
    if (target !== rel) return; // another model was opened meanwhile

    const sources = new Map<string, string>();
    const modelDir = inModels || inLods ? `${itemDir}/models` : dir;
    const base = (models?.files ?? []).find((f: AssetFile) => f.name.toLowerCase() === `${stem}.glb`.toLowerCase());
    sources.set('0', base ? fileUrl(join(modelDir, base.name), base.mtime) : fileUrl(rel, file.mtime));
    for (const f of (lods?.files ?? []) as AssetFile[]) {
      const m = f.name.match(/^(.*)_LOD(\d+)\.glb$/i);
      if (m && m[1].toLowerCase() === stem.toLowerCase()) sources.set(m[2], fileUrl(join(`${itemDir}/lods`, f.name), f.mtime));
    }
    if (!sources.has(clickedLevel)) sources.set(clickedLevel, fileUrl(rel, file.mtime));

    const downloads = ((models?.files ?? []) as AssetFile[])
      .filter((f) => f.name.replace(/\.[^.]+$/, '').toLowerCase() === stem.toLowerCase() && /\.(glb|gltf|fbx|blend|obj)$/i.test(f.name))
      .map((f) => ({ label: f.name.slice(f.name.lastIndexOf('.') + 1).toUpperCase(), href: fileUrl(join(modelDir, f.name)), size: f.size }));

    const item = inv?.items?.find((x: any) => x.id === itemId) ?? null;
    ctx = { audit, item, sources, downloads };
  }

  const src = $derived(ctx.sources.get(level) ?? fileUrl(rel, file.mtime));
  const levels = $derived([...ctx.sources.keys()].sort((a, b) => Number(a) - Number(b)));
  const height = $derived<number | null>(ctx.audit?.height_m ?? null);
  const canFace = $derived(!!height && itemId.startsWith('characters/races/'));
  const title = $derived(ctx.item?.name ?? file.name);
  const geometry = $derived.by(() => {
    const a = ctx.audit;
    if (!a) return `${bytes(file.size)} · ${file.name.slice(file.name.lastIndexOf('.') + 1).toUpperCase()}`;
    const tris = a.triangles ?? a.meshes?.reduce((n: number, m: any) => n + (m.triangles || 0), 0);
    return [tris ? `${tris.toLocaleString()} triangles` : '', a.bones ? `${a.bones} bones` : '',
      a.face_blendshapes ? `${a.face_blendshapes} facial shapes` : ''].filter(Boolean).join(' · ');
  });
  const credits = $derived<any[]>(ctx.audit?.source_credits ?? []);

  // model-viewer's own events.
  $effect(() => {
    const m = mv;
    if (!m) return;
    const onLoad = () => {
      status = 'Drag to inspect';
      clips = [...(m.availableAnimations ?? [])];
      clip = clips[0] ?? '';
      if (clip) { m.animationName = clip; duration = m.duration || 1; }
      m.pause(); m.currentTime = 0; playing = false; time = 0;
    };
    const onError = () => { status = 'The model could not load. ptm may have gone offline; reopen it to try again.'; };
    const onProgress = (e: Event) => {
      const p = (e as CustomEvent).detail?.totalProgress ?? 0;
      // Progress can still trickle in after 'load' (textures, environment): ignore it then.
      if (p < 1 && !m.loaded) status = `Loading from ptm… ${Math.round(p * 100)}%`;
    };
    m.addEventListener('load', onLoad);
    m.addEventListener('error', onError);
    m.addEventListener('progress', onProgress);
    return () => {
      m.removeEventListener('load', onLoad);
      m.removeEventListener('error', onError);
      m.removeEventListener('progress', onProgress);
    };
  });

  $effect(() => { if (mv) mv.exposure = exposure; });

  // While an animation plays, the frame slider follows it.
  $effect(() => {
    if (!playing || !mv) return;
    let raf = 0;
    const tick = () => { time = mv.currentTime; raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  });

  const dist = () => (faceMode && height ? `${height * 0.53}m` : 'auto');
  function frameBody(face: boolean) { // viewer.html's focus(): face = look at the head from the front
    faceMode = face;
    if (!mv) return;
    mv.cameraTarget = faceMode && height ? `auto ${height * 0.92}m auto` : 'auto auto auto';
    mv.cameraOrbit = `0deg 90deg ${dist()}`;
  }
  function angle(deg: number) {
    if (!mv) return;
    mv.autoRotate = spinning = false;
    mv.cameraOrbit = `${deg}deg 90deg ${dist()}`;
  }
  function spin() { if (mv) mv.autoRotate = spinning = !spinning; }
  function pickClip(name: string) {
    clip = name;
    if (!mv) return;
    mv.animationName = name; mv.currentTime = 0; time = 0; duration = mv.duration || 1;
  }
  function play() {
    if (!mv) return;
    if (mv.paused) { mv.play(); playing = true; } else { mv.pause(); playing = false; }
  }
  function rest() { if (!mv) return; mv.pause(); mv.currentTime = 0; time = 0; playing = false; }
  function scrub(t: number) { time = t; if (!mv) return; mv.pause(); playing = false; mv.currentTime = t; }
</script>

<div class="inspector">
  <div class="stage">
    {#if engine !== 'failed'}
      <model-viewer
        bind:this={el}
        {src}
        alt={title}
        camera-controls
        touch-action="pan-y"
        shadow-intensity="1"
        shadow-softness=".8"
        exposure="1"
        camera-orbit="0deg 80deg auto"
        interaction-prompt="none"
        tone-mapping="neutral"
      ></model-viewer>
    {/if}
    <div class="notice">{status}</div>
  </div>

  <aside class="side">
    <div class="kicker">Inspect the actual model</div>
    <h2 class="name" title={file.name}>{title}</h2>
    {#if ctx.item?.category}<div class="faint small">{ctx.item.category}</div>{/if}

    <div class="btns">
      <button class="btn" onclick={() => angle(0)}>Front</button>
      <button class="btn" onclick={() => angle(90)}>Side</button>
      <button class="btn" onclick={() => angle(180)}>Back</button>
      <button class="btn" class:on={spinning} aria-pressed={spinning} onclick={spin}>{spinning ? 'Stop rotation' : 'Rotate'}</button>
    </div>
    {#if canFace}
      <div class="btns">
        <button class="btn" class:on={!faceMode} onclick={() => frameBody(false)}>Full model</button>
        <button class="btn" class:on={faceMode} onclick={() => frameBody(true)}>Face close-up</button>
      </div>
    {/if}

    <label>Mesh detail
      <select class="field" bind:value={level} disabled={levels.length < 2}>
        {#each levels as l (l)}<option value={l}>{l === '0' ? 'LOD 0 · full detail' : `LOD ${l} · distance mesh`}</option>{/each}
      </select>
    </label>
    <p class="stats">{geometry}</p>

    <label>Light exposure
      <input type="range" min=".3" max="2" step=".05" bind:value={exposure} />
    </label>

    <label>Rig animation
      <select class="field" value={clip} onchange={(e) => pickClip(e.currentTarget.value)} disabled={!clips.length}>
        {#each clips as c (c)}<option value={c}>{c.replace(/_RigDiagnostic$/, ' · rig diagnostic')}</option>
        {:else}<option value="">No animation on this asset</option>{/each}
      </select>
    </label>
    <div class="btns">
      <button class="btn" disabled={!clips.length} onclick={play}>{playing ? 'Pause' : 'Play'}</button>
      <button class="btn" disabled={!clips.length} onclick={rest}>Rest pose</button>
    </div>
    <input type="range" aria-label="Animation frame" min="0" max={duration} step=".001" value={time}
      oninput={(e) => scrub(Number(e.currentTarget.value))} disabled={!clips.length} />

    <p class="help faint">Drag to orbit. Scroll or pinch to zoom. Shift-drag or two-finger drag to pan.</p>

    {#if ctx.downloads.length}
      <div class="btns">
        {#each ctx.downloads as d (d.href)}<a class="btn" href={d.href} download title={bytes(d.size)}>{d.label}</a>{/each}
      </div>
    {/if}

    {#if ctx.item || credits.length}
      <details>
        <summary>Source credits and checks</summary>
        {#each credits as c, i (i)}
          <p class="credit">
            {c.author || 'Source artist'} — {c.license || 'See source'}. {c.changes || ''}
            {#if c.source?.startsWith('https://')}<a href={c.source} target="_blank" rel="noreferrer">Source</a>{/if}
          </p>
        {/each}
        {#if ctx.item}
          <p class="faint small">
            {ctx.item.unity_verified ? 'Unity import checked. Inspect the model and equipped fit for your scene.'
              : 'Exported candidate; validation or visual review remains pending.'}
          </p>
        {/if}
      </details>
    {/if}
  </aside>
</div>

<style>
  .inspector {
    display: grid; grid-template-columns: minmax(0, 1fr) 300px;
    height: min(76vh, 860px); min-height: 460px;
    border: 1px solid var(--border); border-radius: var(--r-lg); overflow: hidden; background: var(--surface);
  }
  /* The stage is the library viewer's own look (viewer.html), kept exactly — a fixed
     studio backdrop, not UI chrome, so it does not follow the theme. */
  .stage { position: relative; min-width: 0; background: radial-gradient(ellipse at 50% 40%, #34414a, #171d22 80%); }
  model-viewer { width: 100%; height: 100%; --poster-color: transparent; }
  .notice {
    position: absolute; left: 16px; bottom: 14px; max-width: min(70ch, calc(100% - 32px));
    padding: 8px 12px; border-radius: var(--r-sm); background: rgba(17, 17, 17, .72); color: #c7d2d8;
    font-size: var(--fs-sm); pointer-events: none;
  }
  .side { display: flex; flex-direction: column; gap: 10px; padding: var(--s4); border-left: 1px solid var(--border); overflow-y: auto; }
  .kicker { font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); }
  .name { font-size: var(--fs-lg); overflow-wrap: anywhere; }
  .small { font-size: var(--fs-xs); }
  .btns { display: flex; flex-wrap: wrap; gap: 6px; }
  .btn.on { border-color: var(--accent); color: var(--accent); }
  label { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; font-size: var(--fs-sm); color: var(--ink-2); }
  select.field { width: 100%; }
  input[type='range'] { width: 100%; accent-color: var(--accent); }
  .stats { margin: 0; font-size: var(--fs-sm); color: var(--brand); }
  .help { margin: 4px 0 0; font-size: var(--fs-xs); line-height: 1.5; }
  details { font-size: var(--fs-sm); margin-top: 4px; }
  summary { cursor: pointer; color: var(--ink-2); }
  .credit { margin: 8px 0 0; padding-top: 8px; border-top: 1px solid var(--border); color: var(--ink-2); font-size: var(--fs-xs); }
  @media (max-width: 900px) {
    .inspector { grid-template-columns: minmax(0, 1fr); height: auto; min-height: 0; }
    .stage { height: 62vh; min-height: 320px; }
    .side { border-left: 0; border-top: 1px solid var(--border); }
  }
</style>
