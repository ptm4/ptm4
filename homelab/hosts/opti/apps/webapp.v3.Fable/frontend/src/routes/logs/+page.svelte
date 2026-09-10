<script lang="ts">
  // /logs — container logs as their own page again.
  //
  // The 2026-09-10 nav consolidation folded Logs into a Cockpit tab, and Peter asked
  // for it back as a page (his reference: v2.legacy's full-bleed Dozzle). Fair call —
  // logs are a destination you go to mid-incident, often straight from a phone or a
  // toast, and a destination deserves a URL and a rail entry, not a tab inside another
  // page's state. This is the "place you go" test the nav rules already state, applied
  // honestly.
  //
  // The body IS the Cockpit tab's panel, reused whole — same Dozzle iframe over the
  // same-origin /dozzle proxy (hub on opti since the app-tier move), same container
  // picker deep-linking to /dozzle/container/<id>, same ?c= param. One implementation,
  // two doors; the tab stays because Cockpit workflows link to it.
  import LogsPanel from '../cockpit/_parts/LogsPanel.svelte';
</script>

<LogsPanel />
