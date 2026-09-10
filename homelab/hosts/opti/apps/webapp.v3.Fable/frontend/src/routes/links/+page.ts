import { redirect } from '@sveltejs/kit';

// v2's /links is the Launchpad now; keep the bookmark working.
export function load() {
  redirect(307, '/launchpad');
}
