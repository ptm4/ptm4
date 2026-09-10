import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { get, post, put } from '../lib/api';
import { ALL_LINKS, iconUrl } from '../lib/links';
export type Mode = 'demo' | 'live-readonly';
export interface Host { id:string; role:string; address:string; os:string; cpu:number|null; memory:number|null; temperature:number|null; uptime:number|null; status:string; storage:string; observedAt:string|null; error:string|null }
export interface Service { id:string; name:string; host:string; group:string; url:string|null; icon:string; status:string; image:string|null; observedAt:string|null }
export interface Finding { id:string; host:string|null; severity:string; source:string; message:string; detail:string; ts:string|null }
export interface Snapshot { mode:Mode; observedAt:string; hosts:Host[]; services:Service[]; findings:Finding[]; schedules:{host:string;unit:string;next:string|null;passed:string|null}[]; dns:{dns_queries_today:number|null;ads_percentage_today:number|null;unique_clients:number|null;blocking:{enabled:boolean}|null}|null; errors:{source:string;message:string}[]; sources:{route:string;available:boolean}[] }
export interface Preferences { rev:number; theme:'dark'|'light';density:'comfortable'|'compact';reducedMotion:boolean;favorites:string[];launchers:{id:string;name:string;url:string;group:string}[];acknowledgements:string[];savedViews:{name:string;path:string}[] }
export interface Capabilities { mode:Mode;liveWrites:boolean;localPreferences:boolean;simulatedActions:boolean;legacyUrl:string }
export const useCapabilities = () => useQuery({ queryKey:['astra-capabilities'],queryFn:()=>get<Capabilities>('/api/astra/capabilities'), refetchInterval:30000 });
export function useSnapshot() { const c=useCapabilities(); return useQuery({queryKey:['astra-snapshot',c.data?.mode],queryFn:()=>get<Snapshot>('/api/astra/snapshot',20000),enabled:!!c.data,refetchInterval:30000}); }
export const usePreferences = () => useQuery({queryKey:['astra-preferences'],queryFn:()=>get<Preferences>('/api/astra/preferences'),refetchOnWindowFocus:true});
export function useSavePreferences() { const q=useQueryClient();return useMutation({mutationFn:(p:Preferences)=>put<Preferences>('/api/astra/preferences',p),onSuccess:p=>q.setQueryData(['astra-preferences'],p),onError:()=>q.invalidateQueries({queryKey:['astra-preferences']})}); }
export function useMode() { const q=useQueryClient();return useMutation({mutationFn:(mode:Mode)=>post<{mode:Mode}>('/api/astra/mode',{mode}),onSuccess:()=>q.resetQueries()}); }
export const LEGACY='https://webapp.rpi.lan:8443';
export const tools = [{name:'Notes',path:'/notes/',description:'Your notebooks and pages'},{name:'Streams',path:'/streams/',description:'Stream station and playback'},{name:'Samba',path:'/samba/',description:'Storage share configuration'},{name:'Architecture',path:'/architecture/',description:'Homelab topology and dependencies'},{name:'Agents',path:'/agents/',description:'Specialist agent controls'},{name:'Agentic',path:'/agentic/',description:'Agent workspace and wiring'},{name:'Logs / Dozzle',path:'/dozzle/',description:'Live container log viewer'}];
export function age(value:string|null|undefined) {if(!value)return 'Not observed';const ms=Date.now()-Date.parse(value);if(!Number.isFinite(ms))return value; if(ms<0){const n=-ms;return n>=86400000?`in ${Math.ceil(n/86400000)}d`:n>=3600000?`in ${Math.ceil(n/3600000)}h`:`in ${Math.ceil(n/60000)}m`}if(ms<60000)return 'just now';if(ms<3600000)return `${Math.floor(ms/60000)}m ago`;if(ms<86400000)return `${Math.floor(ms/3600000)}h ago`;return `${Math.floor(ms/86400000)}d ago`;}
export function health(h:Host) { return h.status==='healthy' && (!h.observedAt || Date.now()-Date.parse(h.observedAt)>90000) ? 'stale' : h.status; }
export function launchers(prefs:Preferences|undefined){
 const native=new Set(['/streams/','/samba/','/architecture/','/agents/','/agentic/']);
 const catalog=[...ALL_LINKS.map(l=>({id:l.label.toLowerCase().replace(/[^a-z0-9]+/g,'-'),name:l.label,url:l.url.startsWith('/')?(native.has(l.url)?l.url:LEGACY+l.url):l.url,group:l.group,icon:iconUrl(l.icon),custom:false})),...[
 ['hltv','HLTV matches','https://www.hltv.org/matches'],['blast','BLAST.tv','https://blast.tv/'],['twitch','Twitch','https://www.twitch.tv/'],['github','GitHub','https://github.com/'],['youtube','YouTube','https://www.youtube.com/']
 ].map(([id,name,url])=>({id,name,url,group:'General',icon:'/icons/apps/generic.svg',custom:false}))];
 const merged=new Map(catalog.map(l=>[l.id,l]));
 for(const l of prefs?.launchers||[])merged.set(l.id,{...l,icon:merged.get(l.id)?.icon||'/icons/apps/generic.svg',custom:true});
 return [...merged.values()];
}