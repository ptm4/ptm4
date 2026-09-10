<script lang="ts">
  let { title, phase, note }: { title: string; phase: string; note?: string } = $props();
</script>

<div class="page-stub">
  <div>
    <h2>{title}</h2>
    <p>{note ?? 'This section is being ported to v3.'}</p>
    <span class="phase">{phase}</span>
  </div>
</div>
