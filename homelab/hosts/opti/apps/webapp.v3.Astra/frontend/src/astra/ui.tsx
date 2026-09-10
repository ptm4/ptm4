import { useEffect, useRef, type ReactNode } from 'react';
import { X, ArrowUpRight, Inbox } from 'lucide-react';
import { Link } from 'react-router-dom';
import { age } from './data';
export function Badge({status,children}:{status?:string;children?:ReactNode}) {return <span className={`a-badge ${status||''}`}><i/>{children||status||'unknown'}</span>}
export function Panel({title,aside,children,className=''}:{title:string;aside?:ReactNode;children:ReactNode;className?:string}) {return <section className={`a-panel ${className}`}><div className="a-panel-head"><h2>{title}</h2>{aside}</div>{children}</section>}
export function Heading({eyebrow,title,description,actions}:{eyebrow:string;title:string;description:string;actions?:ReactNode}) {return <div className="a-heading"><div><p className="a-eyebrow">{eyebrow}</p><h1>{title}</h1><p className="a-muted">{description}</p></div>{actions&&<div className="a-heading-actions">{actions}</div>}</div>}
export function Empty({children}:{children:ReactNode}) {return <div className="a-empty"><Inbox size={24}/><p>{children}</p></div>}
export function Stamp({value}:{value:string|null|undefined}) {return <time className="a-stamp" dateTime={value||undefined} title={value||'No observation timestamp'}>{age(value)}</time>}
export function Metric({label,value,unit='%'}:{label:string;value:number|null;unit?:string}) {return <div className="a-metric"><div><span>{label}</span><b>{value===null?'—':Math.round(value)}{value===null?'':unit}</b></div>{unit==='%'&&<div className="a-meter"><i style={{width:`${Math.max(0,Math.min(value||0,100))}%`}}/></div>}</div>}
export function More({to,children}:{to:string;children:ReactNode}) {return <Link className="a-more" to={to}>{children}<ArrowUpRight size={14}/></Link>}
export function Dialog({title,onClose,children}:{title:string;onClose:()=>void;children:ReactNode}) {const ref=useRef<HTMLDialogElement>(null);useEffect(()=>{ref.current?.showModal();const d=ref.current;return()=>d?.close()},[]);return <dialog ref={ref} className="a-dialog" onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose()}}><div className="a-dialog-head"><h2>{title}</h2><button className="a-icon" aria-label="Close dialog" onClick={onClose}><X/></button></div>{children}</dialog>}
export function ErrorText({error}:{error:unknown}) {return error?<p role="alert" className="a-error">{error instanceof Error?error.message:String(error)}</p>:null}
