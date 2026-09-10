import { WIDGET_BY_TYPE } from '../widgets/registry';
export function Instrument({type,options}:{type:string;options?:Record<string,unknown>}) {
 const def=WIDGET_BY_TYPE[type];if(!def)return null;const View=def.component;
 return <div className={'m-instrument m-'+type}><View options={options}/></div>;
}
