// Live container identity from Dozzle's own event stream (same-origin /dozzle).
//
// The arch-agent fragments carry no container IDs, but Dozzle's SSE feed does —
// its `containers-changed` events are the full list with id, state, health and
// started time. Subscribing while the Containers page is open gives us both the
// deep-link IDs (/dozzle/container/<id>) and live state changes for free.
// The isolated preview uses the cached container read-model. Dozzle is an
// explicitly opened specialist link; never open an unreviewed SSE connection.
export interface DozzleContainer {id:string;name:string;state:string;health?:string;startedAt?:string;host:string}
export function useDozzle():{byName:Record<string,DozzleContainer>;live:boolean}{return {byName:{},live:false}}