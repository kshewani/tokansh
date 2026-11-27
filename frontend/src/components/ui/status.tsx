import {AlertCircle,CheckCircle2,Clock3,Info,ShieldAlert} from 'lucide-react';
import {cn} from '../../utils/cn';
export type ViewStatus='UNAVAILABLE'|'PREVIEW_ONLY'|'DRAFT'|'PENDING'|'PROCESSING'|'SUBMITTED'|'COMMITTED'|'FAILED'|'UNKNOWN'|'RECONCILIATION_REQUIRED'|'SIMULATED'|'APPROVED'|'REJECTED'|'ISSUED';
export function Status({value}:{value:ViewStatus|string}){
 const good=value==='COMMITTED';
 const error=['FAILED','REJECTED','RECONCILIATION_REQUIRED','UNAVAILABLE'].includes(value);
 const warn=['PENDING','PROCESSING','SUBMITTED','UNKNOWN','ISSUED'].includes(value);
 const Icon=good?CheckCircle2:error?ShieldAlert:warn?Clock3:Info;
 const label=value==='PREVIEW_ONLY'||value==='SIMULATED'?'ILLUSTRATIVE':value.replaceAll('_',' ');
 return <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold',good?'border-green-200 bg-green-50 text-green-800':error?'border-red-200 bg-red-50 text-red-700':warn?'border-amber-200 bg-amber-50 text-amber-800':'border-slate-200 bg-slate-100 text-slate-700')}><Icon size={12}/>{label}</span>;
}
export function PreviewWarning({compact=false,connected=false}:{compact?:boolean;connected?:boolean}){
 return <div className={cn('flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 text-[#154b7a]',compact?'px-3 py-2 text-xs':'p-4 text-sm')}><AlertCircle className="mt-0.5 shrink-0" size={16}/>{connected?<p><strong>Ledger-linked observations.</strong> ANSH ownership uses DRUNIX observations. REITs, income, research, payments and financing remain clearly labeled illustrative workflows.</p>:<p><strong>Illustrative workspace.</strong> Figures and scenario stages illustrate the intended workflow. No live backend, property approval, bank payment or DRUNIX ledger operation has been verified.</p>}</div>;
}
export function InlineError({message}:{message:string}){return <p role="alert" className="mt-2 flex items-center gap-1 text-xs font-medium text-red-700"><AlertCircle size={14}/>{message}</p>;}
