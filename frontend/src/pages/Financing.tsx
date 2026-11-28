import {loanActions} from '../app/workspace';
import {useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,CheckCircle2,Clock3,Landmark,RefreshCw,ShieldAlert,Wallet} from 'lucide-react';
import {useFinancing} from '../app/financing';
import {financeQuote,moneyINR,rupeesToMinor} from '../api/financing';
import type {FinanceCommand,Loan} from '../api/financing';
import {investorDemo} from '../api/transfers';
import {errorFeedback} from '../api/client';
import {Card,Metric,SectionHeading} from '../components/ui/card';
import {Button} from '../components/ui/button';
import {Field,SelectField,DataRow} from '../components/ui/form';
import {ReviewDialog} from '../components/ui/dialog';

export function ReservationNotice(){return <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900"><ShieldAlert size={18} className="mt-0.5 shrink-0"/><p><strong>Application record — no blockchain lock or legal pledge.</strong> Reserved ANSH remain transferable on DRUNIX until on-chain collateral controls exist. Reservations reduce financing eligibility only, never your displayed transferable balance.</p></div>;}
const labels:Record<string,string>={APPLIED:'Application received',ASSESSED:'Eligibility assessed',APPROVED:'Approved · application reservation',REJECTED:'Not eligible',DISBURSED:'Disbursement recorded',REPAID:'Repayment recorded',RELEASED:'Application reservation released'};
const nextActions:Record<string,{id:string;label:string}>={APPLIED:{id:'assess',label:'Review lender assessment'},ASSESSED:{id:'approve',label:'Approve & reserve'},APPROVED:{id:'disburse',label:'Record disbursement'},DISBURSED:{id:'repay',label:'Record full repayment'},REPAID:{id:'release',label:'Release application reservation'}};
export function LoanDetails({loan,onAction,busy=false,canRepay=true,role='INVESTOR'}:{loan:Loan;onAction:(action:string)=>void;busy?:boolean;canRepay?:boolean;role?:'INVESTOR'|'LENDER'}){
 const permitted=loanActions(role,loan.state);
 const next=nextActions[loan.state];
 return <div className="space-y-5">
  <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-wider text-[#607D9B]">Saved financing application</p><h3 className="mt-1 font-bold text-[#102B4E]">{labels[loan.state]}</h3></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-[#1769AA]">APPLICATION RECORD</span></div>
  <details className="text-xs text-slate-500"><summary>Application reference & frozen terms</summary><p>{loan.id}</p><pre className="whitespace-pre-wrap break-all">{JSON.stringify((loan as unknown as Record<string,unknown>).terms_snapshot||{legacy:true},null,2)}</pre></details><dl><DataRow label="Collateral quantity" value={loan.quantity+' ANSH · '+(loan.reservation_active?'application reserved':'not reserved')}/><DataRow label="Illustrative collateral value" value={moneyINR(loan.collateral_value_minor)}/><DataRow label="Requested LTV / advance rate" value={loan.ltv_percent+'%'}/><DataRow label="Illustrative principal" value={moneyINR(loan.principal_minor)}/><DataRow label="Fixed-term simple interest" value={moneyINR(loan.interest_minor)}/><DataRow label="Principal outstanding" value={moneyINR(loan.outstanding_principal_minor)}/><DataRow label="Full amount due" value={moneyINR(loan.amount_due_minor)}/></dl>
  {loan.assessment&&<div className={'rounded-lg border p-4 '+(loan.assessment.eligible?'border-blue-100 bg-blue-50':'border-amber-200 bg-amber-50')}><p className="text-xs font-bold text-[#102B4E]">Lender decision · application record · {loan.assessment.eligible?'Eligible':'Declined'}</p><p className="mt-2 text-xs text-slate-600">{loan.assessment.reason}</p><p className="mt-2 text-xs text-slate-500">Illustrative risk: {loan.assessment.risk_band} · DRUNIX observed holdings: {loan.assessment.observed_owned} ANSH</p></div>}
  <ol className="space-y-3" aria-label="Financing lifecycle">{loan.timeline.map((event,i)=><li key={i} className="flex gap-3"><CheckCircle2 size={17} className="mt-0.5 shrink-0 text-[#1769AA]"/><div><p className="text-xs font-semibold text-slate-700">{labels[event.state]}</p><time className="mt-1 block text-[11px] text-slate-500" dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()} · recorded action / {event.actor_role.toLowerCase()}</time></div></li>)}</ol>
  {next&&permitted.includes(next.id)&&(canRepay||!['repay','release'].includes(next.id))&&<Button disabled={busy} onClick={()=>onAction(next.id)}>{next.label}<ArrowRight size={14}/></Button>}
  {permitted.includes('reject')&&<Button variant="danger" disabled={busy} onClick={()=>onAction('reject')}>Reject application</Button>}
  {!canRepay&&['DISBURSED','REPAID'].includes(loan.state)&&<p className="text-xs text-slate-500">The investor must confirm repayment and release.</p>}
  {loan.state==='RELEASED'&&<p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Repayment and application reservation release complete. No DRUNIX ownership or lock was changed.</p>}
 </div>;
}
export function FinancingSummary(){
 const {role,loans}=useFinancing();if(role!=='INVESTOR')return null;
 const active=loans.data?.filter(v=>v.reservation_active)||[];
 const principal=active.reduce((sum,v)=>sum+BigInt(v.outstanding_principal_minor),0n);
 return <Card className="mt-5" title="ANSH-backed financing" description="Application record · separate from ledger ownership" action={<Button asChild size="sm" variant="secondary"><Link to="/collateral">Financing studio <ArrowRight size={14}/></Link></Button>}>
  {loans.isPending?<p className="text-sm text-slate-500">Loading saved financing applications…</p>:loans.error?<p role="alert" className="text-sm text-red-700">{errorFeedback(loans.error)}</p>:<div className="grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-slate-500">Active application reservations</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{active.reduce((n,v)=>n+v.quantity,0)} ANSH</p></div><div><p className="text-xs text-slate-500">Principal outstanding</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{moneyINR(String(principal))}</p></div><div><p className="text-xs text-slate-500">Saved applications</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{loans.data?.length||0}</p></div></div>}
  {active.length>0&&<div className="mt-4 flex flex-wrap gap-2">{active.map(v=><span key={v.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{labels[v.state]} · {v.quantity} ANSH</span>)}</div>}
  <div className="mt-4"><ReservationNotice/></div>
 </Card>;
}
export {FinancingStudio as FinancingWorkspace} from './FinancingStudio';
