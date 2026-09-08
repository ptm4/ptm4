import { redirect } from '@sveltejs/kit';

// v2's /dashboard is the board with slug "dashboard"; keep the bookmark working.
export function load() {
  redirect(307, '/b/dashboard');
}
