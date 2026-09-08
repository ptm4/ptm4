<script lang="ts">
  // One HLS player bound to one stream-station slot. Video never touches the API:
  // /hls/slot<N>/index.m3u8 is nginx → noblenumbat, same-origin. hls.js runs in
  // low-latency live mode; Safari gets the native src. A player only attaches while
  // its slot is starting/running, so an idle slot costs nothing.
  import { onDestroy } from 'svelte';
  import Hls from 'hls.js';
  import { Play, Volume2, VolumeX, Maximize2, PictureInPicture2 } from '@lucide/svelte';
  import { hlsUrl } from '$lib/api/streams';

  let {
    slot,
    live = false,
    muted = false,
    active = true,
    label = '',
    onclick,
  }: {
    slot: number;
    /** attach only when the slot has (or is about to have) a playlist */
    live?: boolean;
    muted?: boolean;
    /** the focused player in a multiview grid */
    active?: boolean;
    label?: string;
    onclick?: () => void;
  } = $props();

  let video: HTMLVideoElement;
  let hls: Hls | null = null;
  let needsTap = $state(false);
  let fatal = $state<string | null>(null);
  let buffering = $state(false);
  let isMuted = $state(false);
  $effect(() => { isMuted = muted; });

  function detach() {
    if (hls) { hls.destroy(); hls = null; }
    if (video) { video.removeAttribute('src'); video.load(); }
  }

  function tryPlay() {
    video?.play().then(() => { needsTap = false; }).catch(() => { needsTap = true; });
  }

  function attach(url: string) {
    detach();
    fatal = null;
    if (Hls.isSupported()) {
      hls = new Hls({
        lowLatencyMode: true,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 5,
        maxLiveSyncPlaybackRate: 1.05,
        enableWorker: true,
        manifestLoadingMaxRetry: 30,
        manifestLoadingRetryDelay: 2000,
        levelLoadingMaxRetry: 10,
      });
      hls.loadSource(url);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => tryPlay());
      hls.on(Hls.Events.ERROR, (_e, d) => {
        if (!d.fatal || !hls) return;
        if (d.type === Hls.ErrorTypes.NETWORK_ERROR) hls.startLoad();          // playlist not there yet / hiccup
        else if (d.type === Hls.ErrorTypes.MEDIA_ERROR) hls.recoverMediaError();
        else { fatal = d.details; detach(); }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url;
      tryPlay();
    } else {
      fatal = 'HLS is not supported in this browser';
    }
  }

  $effect(() => {
    const url = hlsUrl(slot);
    if (live) attach(url); else detach();
    return () => detach();
  });
  onDestroy(detach);

  async function pip() {
    try {
      if (document.pictureInPictureElement) await document.exitPictureInPicture();
      else await video.requestPictureInPicture();
    } catch { /* unsupported */ }
  }
  function fullscreen() {
    const el = video.parentElement!;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen?.();
  }
</script>

<div class="player" class:active class:idle={!live} role="presentation" onclick={onclick}>
  <video bind:this={video} playsinline muted={isMuted} onwaiting={() => (buffering = true)} onplaying={() => (buffering = false)} onstalled={() => (buffering = true)}></video>
  {#if label}<span class="label">{label}</span>{/if}
  {#if !live}
    <div class="overlay"><span class="faint">slot {slot} · idle</span></div>
  {:else if fatal}
    <div class="overlay"><span class="t-crit">{fatal}</span></div>
  {:else if needsTap}
    <button class="overlay tap" onclick={(e) => { e.stopPropagation(); tryPlay(); }}><Play size={28} /> Tap to play</button>
  {:else if buffering}
    <div class="overlay soft"><div class="spin"></div></div>
  {/if}
  {#if live && !fatal}
    <div class="ctl" role="group">
      <button title={isMuted ? 'Unmute' : 'Mute'} onclick={(e) => { e.stopPropagation(); isMuted = !isMuted; }}>{#if isMuted}<VolumeX size={15} />{:else}<Volume2 size={15} />{/if}</button>
      <button title="Picture in picture" onclick={(e) => { e.stopPropagation(); pip(); }}><PictureInPicture2 size={15} /></button>
      <button title="Fullscreen" onclick={(e) => { e.stopPropagation(); fullscreen(); }}><Maximize2 size={15} /></button>
    </div>
  {/if}
</div>

<style>
  .player { position: relative; aspect-ratio: 16 / 9; background: #000; border-radius: var(--r); overflow: hidden; border: 1px solid var(--border); }
  .player.active { border-color: var(--accent-muted); }
  .player.idle { background: var(--bg-inset); }
  video { width: 100%; height: 100%; display: block; object-fit: contain; background: #000; }
  .label { position: absolute; top: 8px; left: 10px; font: 600 11px var(--mono); color: var(--ink); background: rgba(0,0,0,.55); border-radius: 4px; padding: 2px 7px; pointer-events: none; }
  .overlay { position: absolute; inset: 0; display: grid; place-items: center; font-size: 13px; color: var(--ink-2); background: rgba(0,0,0,.35); }
  .overlay.soft { background: none; }
  .overlay.tap { border: 0; color: var(--ink); font: 600 15px var(--sans); cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; background: rgba(0,0,0,.5); }
  .ctl { position: absolute; right: 8px; bottom: 8px; display: flex; gap: 4px; opacity: 0; transition: opacity .15s; }
  .player:hover .ctl, .player:focus-within .ctl { opacity: 1; }
  @media (pointer: coarse) { .ctl { opacity: 1; } }
  .ctl button { border: 0; background: rgba(0,0,0,.6); color: var(--ink); border-radius: var(--r-sm); width: 30px; height: 30px; display: grid; place-items: center; cursor: pointer; }
  .ctl button:hover { background: rgba(0,0,0,.85); color: var(--accent); }
</style>
