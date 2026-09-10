<script lang="ts">
  // Generic field renderer driven by BotDef.fields — every bot's plain settings
  // (time/text/password/number/boolean/select) share this one form.
  import type { BotConfig, BotField } from '$lib/bots';

  let { fields, form = $bindable() }: { fields: BotField[]; form: BotConfig } = $props();
</script>

<div class="form-rows">
  {#each fields as f (f.key)}
    <label class="form-row">
      <span>{f.label}</span>
      {#if f.type === 'boolean'}
        <input type="checkbox" checked={form[f.key] === true}
          oninput={(e) => (form = { ...form, [f.key]: e.currentTarget.checked })} />
      {:else if f.type === 'select'}
        <select value={String(form[f.key] ?? '')}
          onchange={(e) => (form = { ...form, [f.key]: e.currentTarget.value })}>
          {#each f.choices ?? [] as c (c.value)}
            <option value={c.value}>{c.label}</option>
          {/each}
        </select>
      {:else}
        <input
          type={f.type === 'time' ? 'time' : f.type === 'number' ? 'number' : f.type === 'password' ? 'password' : 'text'}
          value={String(form[f.key] ?? '')}
          placeholder={f.placeholder}
          oninput={(e) => (form = {
            ...form,
            [f.key]: f.type === 'number' ? Number(e.currentTarget.value) : e.currentTarget.value,
          })}
        />
      {/if}
      {#if f.help}<span class="form-help t-dim">{f.help}</span>{/if}
    </label>
  {/each}
</div>
