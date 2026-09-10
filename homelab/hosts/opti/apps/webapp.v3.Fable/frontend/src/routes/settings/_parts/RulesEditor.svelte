<script lang="ts">
  // Alert rules editor — thresholds the backend evaluates every minute. A firing rule
  // is a finding: it reaches the bell, the incidents page and the feed.
  import { Plus, Trash2, Play, RotateCcw } from '@lucide/svelte';
  import { useRules, useRuleActions, NUMERIC_KINDS, KIND_LABEL, type Rule, type RuleKind } from '$lib/api/rules';
  import { HOSTS } from '$lib/nav';
  import { toast } from '$lib/stores/toast.svelte';
  import { confirm } from '$lib/stores/confirm.svelte';
  import { relTime } from '$lib/format';

  const q = useRules();
  const { create, update, remove, reset, evaluate } = useRuleActions();

  let draft = $state<Omit<Rule, 'id'>>({ name: '', enabled: true, kind: 'disk', host: null, container: null, op: '>', threshold: 80, for_min: 0, severity: 'warn' });
  let adding = $state(false);
  const numeric = (k: RuleKind) => NUMERIC_KINDS.includes(k);

  async function patch(r: Rule, p: Partial<Rule>) {
    try { await update.mutateAsync({ id: r.id, ...p }); } catch (e) { toast(`Could not save rule: ${(e as Error).message}`, 'crit'); }
  }
  async function add(e: Event) {
    e.preventDefault();
    try { await create.mutateAsync({ ...draft, container: draft.container || null, host: draft.host || null }); adding = false; draft = { ...draft, name: '' }; toast('Rule added', 'ok', { ttlMs: 2000 }); }
    catch (err) { toast(`Could not add: ${(err as Error).message}`, 'crit'); }
  }
  async function del(r: Rule) {
    if (!(await confirm({ title: `Delete rule “${r.name}”?`, body: 'It stops firing immediately; existing findings from it clear on the next evaluation.', tone: 'crit', confirmLabel: 'Delete' }))) return;
    try { await remove.mutateAsync(r.id); } catch (e) { toast(`Could not delete: ${(e as Error).message}`, 'crit'); }
  }
  async function doReset() {
    if (!(await confirm({ title: 'Reset to the default rules?', body: 'Your custom rules are replaced by the built-in set.', tone: 'warn', confirmLabel: 'Reset' }))) return;
    await reset.mutateAsync();
  }
  async function runNow() {
    try { const r = await evaluate.mutateAsync(); toast(`Evaluated — ${r.hits.length} rule${r.hits.length === 1 ? '' : 's'} firing`, 'ok', { ttlMs: 3000 }); }
    catch (e) { toast(`Evaluate failed: ${(e as Error).message}`, 'crit'); }
  }
</script>

<section class="card c12 rules">
  <div class="chead">
    <h3>Alert rules</h3>
    <span class="meta">{q.data ? `${q.data.hits.length} firing · evaluated ${relTime(q.data.evaluated_at)}` : q.isError ? 'unavailable on this backend' : '…'}</span>
    <div class="right">
      <button class="tbtn sm" disabled={evaluate.isPending} onclick={runNow}><Play /> Evaluate now</button>
      <button class="tbtn sm" onclick={doReset}><RotateCcw /> Defaults</button>
      <button class="tbtn sm primary" onclick={() => (adding = !adding)}><Plus /> Rule</button>
    </div>
  </div>
  {#if q.isError}<p class="err">This backend has no <code>/api/rules</code>.</p>{/if}

  {#if adding}
    <form class="draft" onsubmit={add}>
      <input class="input" placeholder="Name" bind:value={draft.name} required />
      <select class="input" bind:value={draft.kind}>{#each Object.entries(KIND_LABEL) as [k, l] (k)}<option value={k}>{l}</option>{/each}</select>
      <select class="input" bind:value={draft.host}><option value={null}>any host</option>{#each HOSTS as h (h.name)}<option value={h.name}>{h.name}</option>{/each}</select>
      {#if draft.kind === 'container_down'}<input class="input" placeholder="container (blank = any)" bind:value={draft.container} />{/if}
      {#if numeric(draft.kind)}
        <select class="input op" bind:value={draft.op}><option value=">">&gt;</option><option value="<">&lt;</option></select>
        <input class="input num" type="number" bind:value={draft.threshold} />
      {/if}
      <label class="for">for <input class="input num" type="number" min="0" max="1440" bind:value={draft.for_min} /> min</label>
      <select class="input" bind:value={draft.severity}><option value="warn">warn</option><option value="critical">critical</option></select>
      <button class="tbtn primary" type="submit" disabled={create.isPending}>Add</button>
    </form>
  {/if}

  <div class="tablewrap">
    <table class="t">
      <thead><tr><th></th><th>Rule</th><th>Condition</th><th>Scope</th><th>Sustain</th><th>Severity</th><th>Firing</th><th></th></tr></thead>
      <tbody>
        {#each q.data?.rules ?? [] as r (r.id)}
          {@const hits = (q.data?.hits ?? []).filter((h) => h.rule_id === r.id)}
          <tr class:off={!r.enabled}>
            <td><input type="checkbox" checked={r.enabled} onchange={(e) => patch(r, { enabled: e.currentTarget.checked })} /></td>
            <td><input class="inline" value={r.name} onchange={(e) => patch(r, { name: e.currentTarget.value })} /></td>
            <td>
              {KIND_LABEL[r.kind]}
              {#if numeric(r.kind)}
                <select class="inline op" value={r.op} onchange={(e) => patch(r, { op: e.currentTarget.value as '>' | '<' })}><option value=">">&gt;</option><option value="<">&lt;</option></select>
                <input class="inline num" type="number" value={r.threshold} onchange={(e) => patch(r, { threshold: Number(e.currentTarget.value) })} />
              {/if}
            </td>
            <td class="faint">{r.host ?? 'any host'}{r.container ? ` · ${r.container}` : ''}</td>
            <td><input class="inline num" type="number" min="0" max="1440" value={r.for_min ?? 0} onchange={(e) => patch(r, { for_min: Number(e.currentTarget.value) })} /> <span class="faint">min</span></td>
            <td><select class="inline" value={r.severity} onchange={(e) => patch(r, { severity: e.currentTarget.value as 'warn' | 'critical' })}><option value="warn">warn</option><option value="critical">critical</option></select></td>
            <td>{#if hits.length}<span class="chip" data-s={r.severity === 'critical' ? 'crit' : 'warn'} title={hits.map((h) => h.message).join('\n')}>{hits.length}</span>{:else}<span class="faint">—</span>{/if}</td>
            <td><button class="tbtn sm icon danger" title="Delete" onclick={() => del(r)}><Trash2 /></button></td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .rules { gap: 10px; }
  .chead .right { margin-left: auto; display: flex; gap: 6px; }
  .draft { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 8px; border: 1px dashed var(--border-2); border-radius: var(--r); }
  .draft .input { min-width: 0; }
  .num { width: 70px; }
  .op { width: 52px; }
  .for { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--ink-3); }
  .inline { background: transparent; border: 1px solid transparent; color: var(--ink); font: inherit; font-size: 12.5px; padding: 2px 4px; border-radius: 4px; }
  .inline:hover, .inline:focus { border-color: var(--border-2); background: var(--bg-inset); outline: none; }
  tr.off { opacity: .5; }
</style>
