<script lang="ts">
  // The app's only innerHTML sink. Finding messages and LLM answers echo raw text
  // (nginx access logs carry attacker-controlled paths), so everything goes through
  // dompurify — keep it that way.
  import { marked } from 'marked';
  import DOMPurify from 'dompurify';

  let { source }: { source: string } = $props();
  let html = $derived(DOMPurify.sanitize(marked.parse(source ?? '', { async: false }) as string));
</script>

<div class="md">{@html html}</div>
