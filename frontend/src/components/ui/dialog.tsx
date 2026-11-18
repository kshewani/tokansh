import * as Dialog from '@radix-ui/react-dialog';
import type {ReactNode} from 'react';
import {X} from 'lucide-react';
import {Button} from './button';
import {useId,useRef,useState} from 'react';
import {confirmReview,createSubmissionGuard} from '../../app/integration';
import {errorFeedback} from '../../api/client';
export function ReviewDialog({open,onOpenChange,title,description,children,onConfirm,confirmLabel='Confirm',busy=false}:{open:boolean;onOpenChange:(v:boolean)=>void;title:string;description:string;children:ReactNode;onConfirm:()=>void|Promise<void>;confirmLabel?:string;busy?:boolean}){
 const [error,setError]=useState<string|null>(null);
 const [confirming,setConfirming]=useState(false);
 const guard=useRef(createSubmissionGuard());
 const descriptionId=useId();
 const pending=busy||confirming;
 function changeOpen(value:boolean){
  if(busy||guard.current.pending)return;
  // Keep an unresolved operation visible when the same dialog is reopened.
  if(!guard.current.blocked)setError(null);
  onOpenChange(value);
 }
 async function confirm(){
  if(busy||guard.current.pending||guard.current.blocked)return;
  setError(null);
  setConfirming(true);
  try {await confirmReview(()=>guard.current.run(onConfirm),error=>setError(errorFeedback(error)));}
  finally {setConfirming(false);}
 }
 return <Dialog.Root open={open} onOpenChange={changeOpen}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-[150] bg-slate-950/55"/>
 <Dialog.Content className="fixed left-1/2 top-1/2 z-[151] max-h-[90dvh] w-[min(92vw,530px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl bg-white p-6 shadow-2xl" aria-describedby={descriptionId} aria-busy={pending}>
 <div className="flex items-start justify-between gap-4"><Dialog.Title className="text-lg font-bold text-[#102B4E]">{title}</Dialog.Title><Dialog.Close disabled={pending} className="rounded p-1 text-slate-500 hover:bg-slate-100" aria-label="Close"><X size={19}/></Dialog.Close></div>
 <Dialog.Description id={descriptionId} className="mt-2 text-sm text-slate-500">{description}</Dialog.Description>
 <div className="my-5 rounded-lg border border-slate-200 bg-slate-50 p-4">{children}</div>
 {error&&<p role="alert" className="mb-4 text-sm text-red-700">{error}</p>}
 <div className="flex justify-end gap-2"><Button variant="secondary" disabled={pending} onClick={()=>changeOpen(false)}>Cancel</Button><Button onClick={confirm} disabled={pending||guard.current.blocked}>{pending?'Submitting…':guard.current.blocked?'Reconciliation required':confirmLabel}</Button></div>
 </Dialog.Content></Dialog.Portal></Dialog.Root>;
}
