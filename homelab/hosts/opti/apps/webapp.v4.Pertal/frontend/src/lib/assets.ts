// Asset Library helpers: where ptm's files are, and what each kind of file is.
// /asset-files and /asset-thumbs are same-origin paths; nginx (prod) and vite (dev) pass
// them straight to the asset server on ptm (homelab/hosts/ptm/asset-server).

export type AssetKind = 'model' | 'image' | 'text' | 'page' | 'other';

const MODEL = new Set(['glb', 'gltf']);
const WEB_IMAGE = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg', 'bmp', 'avif', 'ico']);
const THUMB_ONLY = new Set(['tga', 'tif', 'tiff']); // browsers can't draw these; the server's thumbnail can
const THUMBABLE = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tga', 'tif', 'tiff']);
const TEXT = new Set(['json', 'md', 'txt', 'log', 'csv', 'py', 'cs', 'yaml', 'yml', 'ini', 'cfg', 'toml',
  'ps1', 'sh', 'bat', 'xml', 'shader', 'hlsl', 'glsl']);
const PAGE = new Set(['html', 'htm']);

export const ext = (name: string) => (name.includes('.') ? name.slice(name.lastIndexOf('.') + 1).toLowerCase() : '');

export function kindOf(name: string): AssetKind {
  const e = ext(name);
  if (MODEL.has(e)) return 'model';
  if (WEB_IMAGE.has(e) || THUMB_ONLY.has(e)) return 'image';
  if (TEXT.has(e)) return 'text';
  if (PAGE.has(e)) return 'page';
  return 'other';
}

export const hasThumb = (name: string) => THUMBABLE.has(ext(name));
export const browserCanShow = (name: string) => WEB_IMAGE.has(ext(name));

const enc = (rel: string) => rel.split('/').map(encodeURIComponent).join('/');
/** The file itself. `v` (its mtime) makes a changed file a new URL. */
export const fileUrl = (rel: string, v?: number) => `/asset-files/${enc(rel)}${v ? `?v=${v}` : ''}`;
/** A JPEG no larger than `w` px, made and cached on ptm. */
export const thumbUrl = (rel: string, w = 320, v?: number) => `/asset-thumbs/${enc(rel)}?w=${w}${v ? `&v=${v}` : ''}`;

export const join = (dir: string, name: string) => (dir ? `${dir}/${name}` : name);
export const parentOf = (rel: string) => (rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '');
export const baseName = (rel: string) => rel.slice(rel.lastIndexOf('/') + 1);

/** Every folder from the root down to `rel`: '', 'a', 'a/b', … */
export function ancestors(rel: string): string[] {
  const out = [''];
  let acc = '';
  for (const seg of rel.split('/').filter(Boolean)) out.push((acc = join(acc, seg)));
  return out;
}

// The library's own pages, opened as they are (they work unchanged under /asset-files/).
export const GALLERIES = [
  { root: 'DND5E', path: 'DND5E/index.html', label: 'Library gallery' },
  { root: 'DND5E', path: 'DND5E/hd/index.html', label: 'HD characters' },
  { root: 'DND5E', path: 'DND5E/hd/style_compare.html', label: 'Style comparison' },
];
