import { WIDGET_BY_TYPE } from '../widgets/registry';
import { WidgetCtx } from '../board/widget-ctx';
import { LEGACY } from './data';
const areas:Record<string,string[]>={media:['downloads','streams'],weather:['weather'],gaming:['cs2-matches','leetify-trend'],price:['price-watch'],bots:['bots']};
export default function Widgets({area}:{area:string}) {return <><p className="a-inline-notice">Existing integrations, in this workspace. Unavailable sources show an explicit error. Operational requests remain blocked by the preview backend.</p><div className="a-integration-grid">{(areas[area]||[]).map(type=>{const def=WIDGET_BY_TYPE[type];if(!def)return null;const View=def.component;return <div key={type} className="a-integration"><WidgetCtx.Provider value={{updateOptions:()=>{}}}><View/></WidgetCtx.Provider></div>})}</div><p className="a-stamp">Specialist controls remain in the <a href={LEGACY} target="_blank" rel="noreferrer">existing site</a>.</p></>}
