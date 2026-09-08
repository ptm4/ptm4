// SPA: no server rendering, no prerendering. adapter-static emits dist/index.html as
// the fallback shell and the Fastify static plugin serves it for every HTML route.
export const ssr = false;
export const prerender = false;
export const trailingSlash = 'never';
