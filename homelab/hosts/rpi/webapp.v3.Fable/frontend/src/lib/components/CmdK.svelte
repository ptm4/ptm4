<script lang="ts">
  // Command palette — go anywhere, open any app, run the two fleet-wide actions, or
  // fall through to the runbook-grounded local LLM when nothing matches.
  import { goto } from '$app/navigation';
  import { Dialog, Command } from 'bits-ui';
  import { Boxes, BrainCircuit, RefreshCw, Stethoscope, SunMoon, Palette, TrendingUp, Server } from '@lucide/svelte';
  import { NAV, HOSTS } from '$lib/nav';
  import { ALL_LINKS, iconUrl, isExternal } from '$lib/links';
  import { app } from '$lib/stores/ui.svelte';
  import { ui } from '$lib/stores/theme.svelte';
  import { post } from '$lib/api/client';
  import { toast } from '$lib/stores/toast.svelte';
  import { useContainers } from '$lib/api/queries';
  import Modal from './Modal.svelte';
  import Markdown from './Markdown.svelte';

  const containers = useContainers();
  let query = $state('');
  let asking = $state(false);
  let answer = $state<{ q: string; a: string } | null>(null);

  const pages = NAV.flatMap((g) => g.items.filter((i) => !i.external));
  const external = NAV.flatMap((g) => g.items.filter((i) => i.external));

  const run = (fn: () => void) => { app.setCmdk(false); query = ''; fn(); };
  const go = (path: string) => run(() => { goto(path); });
  const openHref = (href: string) => run(() => {
    if (isExternal(href)) window.open(href, '_blank', 'noreferrer');
    else window.location.href = href;
  });

  let allContainers = $derived((containers.data?.hosts ?? [])
    .flatMap((h) => h.containers.map((c) => ({ ...c, host: h.host }))));

  // No palette match → offer the question to the runbook-grounded local LLM. The
  // answer modal outlives the palette — a 60s round trip shouldn't die with it.
  async function askHomelab(q: string) {
    asking = true;
    toast('Asking the local LLM… this can take a minute on the phone', 'info');
    try {
      const d = await post<{ answer?: string; error?: string }>('/api/llama/ask', { question: q }, 185_000);
      answer = { q, a: d.answer ?? d.error ?? '(no answer)' };
      app.setCmdk(false);
    } catch (e) {
      toast(`Ask failed: ${(e as Error).message}`, 'crit');
    } finally {
      asking = false;
    }
  }

  async function runDoctor() {
    toast('Doctor run requested…');
    try {
      await post('/api/runners/homelab-doctor/run');
      toast('Homelab Doctor queued — results within a minute or two', 'ok');
    } catch (e) {
      toast(`Doctor run failed: ${(e as Error).message}`, 'crit');
    }
  }

  async function syncAll() {
    toast('Force Sync requested on all agents…');
    try {
      await post('/api/agents/sync-all', undefined, 30_000);
      toast('Agents synced', 'ok');
    } catch (e) {
      toast(`Sync failed: ${(e as Error).message}`, 'crit');
    }
  }
</script>

<Dialog.Root open={app.cmdkOpen} onOpenChange={(v) => { app.setCmdk(v); if (!v) query = ''; }}>
  <Dialog.Portal>
    <Dialog.Overlay class="cmdk-overlay" />
    <Dialog.Content class="cmdk">
      <Dialog.Title class="sr-only">Command palette</Dialog.Title>
      <Command.Root label="Command palette" loop>
        <Command.Input class="cmdk-input" placeholder="Go to, open, run — or ask a question…" bind:value={query} />
        <Command.List class="cmdk-list">
          <Command.Viewport>
            <Command.Empty class="cmdk-empty">
              {#if query.trim().length > 3}
                <button class="tbtn" disabled={asking} onclick={() => askHomelab(query.trim())}>
                  <BrainCircuit /> {asking ? 'Asking the local LLM…' : `Ask the homelab: “${query.trim()}”`}
                </button>
              {:else}
                Nothing matches.
              {/if}
            </Command.Empty>

            <Command.Group value="go">
              <Command.GroupHeading class="cmdk-heading">Go to</Command.GroupHeading>
              <Command.GroupItems>
                {#each pages as p (p.path)}
                  {@const Icon = p.icon}
                  <Command.Item class="cmdk-item" value="go {p.label}" onSelect={() => go(p.path)}>
                    <Icon aria-hidden="true" /> {p.label}
                  </Command.Item>
                {/each}
                {#each HOSTS as h (h.name)}
                  <Command.Item class="cmdk-item" value="host {h.name}" onSelect={() => go(`/host/${h.name}`)}>
                    <Server aria-hidden="true" /> {h.label} <span class="hint">{h.role}</span>
                  </Command.Item>
                {/each}
              </Command.GroupItems>
            </Command.Group>

            <Command.Group value="open">
              <Command.GroupHeading class="cmdk-heading">Open</Command.GroupHeading>
              <Command.GroupItems>
                {#each external as p (p.path)}
                  {@const Icon = p.icon}
                  <Command.Item class="cmdk-item" value="open {p.label}" onSelect={() => openHref(p.path)}>
                    <Icon aria-hidden="true" /> {p.label} <span class="hint">page</span>
                  </Command.Item>
                {/each}
                <Command.Item class="cmdk-item" value="open legacy ui v1" onSelect={() => openHref('/legacy/')}>
                  <Boxes aria-hidden="true" /> Legacy UI <span class="hint">v1</span>
                </Command.Item>
              </Command.GroupItems>
            </Command.Group>

            <Command.Group value="apps">
              <Command.GroupHeading class="cmdk-heading">Apps</Command.GroupHeading>
              <Command.GroupItems>
                {#each ALL_LINKS as l (l.label)}
                  <Command.Item class="cmdk-item" value="app {l.label}" onSelect={() => openHref(l.url)}>
                    <img src={iconUrl(l.icon)} alt="" width="14" height="14" />
                    {l.label} <span class="hint">{l.group}</span>
                  </Command.Item>
                {/each}
              </Command.GroupItems>
            </Command.Group>

            {#if allContainers.length > 0}
              <Command.Group value="containers">
                <Command.GroupHeading class="cmdk-heading">Containers</Command.GroupHeading>
                <Command.GroupItems>
                  {#each allContainers as c (`${c.host}/${c.name}`)}
                    <Command.Item class="cmdk-item" value="container {c.name} {c.host}" onSelect={() => go('/containers')}>
                      <Boxes aria-hidden="true" /> {c.name}
                      <span class="hint">{c.host} · {c.up ? 'up' : 'down'}{c.update_available ? ' · update' : ''}</span>
                    </Command.Item>
                  {/each}
                </Command.GroupItems>
              </Command.Group>
            {/if}

            <Command.Group value="actions">
              <Command.GroupHeading class="cmdk-heading">Actions</Command.GroupHeading>
              <Command.GroupItems>
                <Command.Item class="cmdk-item" value="action open updates queue" onSelect={() => go('/updates')}>
                  <TrendingUp aria-hidden="true" /> Open the updates queue
                </Command.Item>
                <Command.Item class="cmdk-item" value="action run homelab doctor" onSelect={() => run(runDoctor)}>
                  <Stethoscope aria-hidden="true" /> Run Homelab Doctor
                </Command.Item>
                <Command.Item class="cmdk-item" value="action force sync all agents" onSelect={() => run(syncAll)}>
                  <RefreshCw aria-hidden="true" /> Force Sync all agents
                </Command.Item>
                <Command.Item class="cmdk-item" value="action toggle theme dark light" onSelect={() => run(() => ui.toggleTheme())}>
                  <SunMoon aria-hidden="true" /> Toggle theme <span class="hint">{ui.theme}</span>
                </Command.Item>
                <Command.Item class="cmdk-item" value="action accent yellow orange aqua" onSelect={() => run(() => ui.cycleAccent())}>
                  <Palette aria-hidden="true" /> Cycle accent <span class="hint">{ui.accent}</span>
                </Command.Item>
              </Command.GroupItems>
            </Command.Group>
          </Command.Viewport>
        </Command.List>
      </Command.Root>
    </Dialog.Content>
  </Dialog.Portal>
</Dialog.Root>

{#if answer}
  <Modal open title="Ask the homelab — {answer.q}" wide onclose={() => (answer = null)}>
    <Markdown source={answer.a} />
  </Modal>
{/if}
