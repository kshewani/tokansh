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

export function ReservationNotice(){return <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900"><ShieldAlert size={18} className="mt-0.5 shrink-0"/><p><strong>Simulation only — no blockchain lock or legal pledge.</strong> Reserved ANSH remain transferable on DRUNIX until on-chain collateral controls exist. Reservations reduce financing eligibility only, never your displayed transferable balance.</p></div>;}
const labels:Record<string,string>={APPLIED:'Application received',ASSESSED:'Eligibility assessed',APPROVED:'Approved · simulation reservation',REJECTED:'Not eligible',DISBURSED:'Disbursement simulated',REPAID:'Repayment simulated',RELEASED:'Simulation reservation released'};
const nextActions:Record<string,{id:string;label:string}>={APPLIED:{id:'assess',label:'Simulate lender assessment'},ASSESSED:{id:'approve',label:'Simulate approval & reserve'},APPROVED:{id:'disburse',label:'Simulate disbursement'},DISBURSED:{id:'repay',label:'Simulate full repayment'},REPAID:{id:'release',label:'Release simulation reservation'}};
export function LoanDetails({loan,onAction,busy=false,canRepay=true}:{loan:Loan;onAction:(action:string)=>void;busy?:boolean;canRepay?:boolean}){
 const next=nextActions[loan.state];
 return <div className="space-y-5">
  <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-[10px] font-bold uppercase tracking-wider text-[#607D9B]">Saved financing application</p><h3 className="mt-1 font-bold text-[#102B4E]">{labels[loan.state]}</h3></div><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-[#1769AA]">SIMULATED</span></div>
  <dl><DataRow label="Application reference" value={<span className="break-all font-mono text-xs">{loan.id}</span>}/><DataRow label="Collateral quantity" value={loan.quantity+' ANSH · '+(loan.reservation_active?'simulation reserved':'not reserved')}/><DataRow label="Illustrative collateral value" value={moneyINR(loan.collateral_value_minor)}/><DataRow label="Requested LTV / advance rate" value={loan.ltv_percent+'%'}/><DataRow label="Illustrative principal" value={moneyINR(loan.principal_minor)}/><DataRow label="Fixed-term simple interest" value={moneyINR(loan.interest_minor)}/><DataRow label="Principal outstanding · simulation" value={moneyINR(loan.outstanding_principal_minor)}/><DataRow label="Full amount due · simulation" value={moneyINR(loan.amount_due_minor)}/></dl>
  {loan.assessment&&<div className={'rounded-lg border p-4 '+(loan.assessment.eligible?'border-blue-100 bg-blue-50':'border-amber-200 bg-amber-50')}><p className="text-xs font-bold text-[#102B4E]">Simulated lender decision · {loan.assessment.eligible?'Eligible':'Declined'}</p><p className="mt-2 text-xs text-slate-600">{loan.assessment.reason}</p><p className="mt-2 text-xs text-slate-500">Illustrative risk: {loan.assessment.risk_band} · DRUNIX observed holdings: {loan.assessment.observed_owned} ANSH</p></div>}
  <ol className="space-y-3" aria-label="Financing lifecycle">{loan.timeline.map((event,i)=><li key={i} className="flex gap-3"><CheckCircle2 size={17} className="mt-0.5 shrink-0 text-[#1769AA]"/><div><p className="text-xs font-semibold text-slate-700">{labels[event.state]}</p><time className="mt-1 block text-[11px] text-slate-500" dateTime={event.timestamp}>{new Date(event.timestamp).toLocaleString()} · simulated action / {event.actor_role.toLowerCase()}</time></div></li>)}</ol>
  {next&&(canRepay||!['repay','release'].includes(next.id))&&<Button disabled={busy} onClick={()=>onAction(next.id)}>{next.label}<ArrowRight size={14}/></Button>}
  {!canRepay&&['DISBURSED','REPAID'].includes(loan.state)&&<p className="text-xs text-slate-500">The investor must confirm repayment and release.</p>}
  {loan.state==='RELEASED'&&<p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">Repayment and simulation release complete. No DRUNIX ownership or lock was changed.</p>}
 </div>;
}
export function FinancingSummary(){
 const {role,loans}=useFinancing();if(role!=='INVESTOR')return null;
 const active=loans.data?.filter(v=>v.reservation_active)||[];
 const principal=active.reduce((sum,v)=>sum+BigInt(v.outstanding_principal_minor),0n);
 return <Card className="mt-5" title="ANSH-backed financing" description="Application-state simulation · separate from ledger ownership" action={<Button asChild size="sm" variant="secondary"><Link to="/collateral">Financing studio <ArrowRight size={14}/></Link></Button>}>
  {loans.isPending?<p className="text-sm text-slate-500">Loading saved financing applications…</p>:loans.error?<p role="alert" className="text-sm text-red-700">{errorFeedback(loans.error)}</p>:<div className="grid gap-4 sm:grid-cols-3"><div><p className="text-xs text-slate-500">Active simulation reservations</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{active.reduce((n,v)=>n+v.quantity,0)} ANSH</p></div><div><p className="text-xs text-slate-500">Simulated principal outstanding</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{moneyINR(String(principal))}</p></div><div><p className="text-xs text-slate-500">Saved applications</p><p className="mt-2 text-xl font-bold text-[#102B4E]">{loans.data?.length||0}</p></div></div>}
  {active.length>0&&<div className="mt-4 flex flex-wrap gap-2">{active.map(v=><span key={v.id} className="rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-600">{labels[v.state]} · {v.quantity} ANSH</span>)}</div>}
  <div className="mt-4"><ReservationNotice/></div>
 </Card>;
}
export function FinancingWorkspace(){
 const {role,loans,eligibility,mutation,apply,action,refresh,newApplication}=useFinancing();
 const [quantity,setQuantity]=useState('1'),[price,setPrice]=useState('10000'),[ltv,setLtv]=useState(60),[rate,setRate]=useState(1000),[months,setMonths]=useState(12);
 const [selected,setSelected]=useState<string|null>(null),[review,setReview]=useState<'apply'|string|null>(null);
 const current=loans.data?.find(v=>v.id===selected)||loans.data?.[0];
 const e=eligibility.isSuccess&&!eligibility.isFetching?eligibility.data:null;
 let estimate:ReturnType<typeof financeQuote>|null=null,command:FinanceCommand|null=null;
 try{if(!/^[1-9][0-9]*$/.test(quantity))throw new Error();const unit=rupeesToMinor(price);estimate=financeQuote(Number(quantity),unit,ltv,rate,months);command={property_id:investorDemo.property,asset_class:'ANSH',quantity:Number(quantity),unit_value_minor:unit,ltv_percent:ltv,annual_rate_bps:rate,term_months:months};}catch{/* Invalid/incomplete form never becomes a quote. */}
 const allowed=!!command&&!!e&&command.quantity<=e.eligible_simulated&&!mutation.isPending;
 async function confirm(){
  if(review==='apply'&&command){const result=await apply(command);setSelected(result.id);}
  else if(review&&current){await action(current.id,review);}
  setReview(null);
 }
 const reviewLabels:Record<string,string>={apply:'Submit financing application',assess:'Simulate eligibility assessment',approve:'Approve & reserve in simulation',disburse:'Simulate loan disbursement',repay:'Simulate full repayment',release:'Release simulation reservation'};
 return <><SectionHeading title={role==='LENDER'?'Simulated Lender Console':'ANSH-backed Liquidity'} description="Explore liquidity against fractional real-estate holdings without selling the asset. Lending decisions and funds are simulated." action={<Button variant="secondary" disabled={loans.isFetching||eligibility.isFetching} onClick={refresh}><RefreshCw size={14}/> Refresh observations</Button>}/>
  <div className="mb-5"><ReservationNotice/></div>
  {role==='INVESTOR'&&<><div className="grid gap-4 sm:grid-cols-3"><Metric label="DRUNIX-owned ANSH" value={e?e.owned+' ANSH':eligibility.isFetching?'Loading…':'—'} description="Fresh ownership evaluation"/><Metric label="Reserved for financing · simulated" value={e?e.reserved_simulated+' ANSH':'—'} description="Not a transferable-balance deduction"/><Metric label="Eligible for this simulation" value={e?e.eligible_simulated+' ANSH':'—'} description="Owned less active simulation reservations"/></div>
   {eligibility.error&&<p role="alert" className="mt-3 text-sm text-red-700">{errorFeedback(eligibility.error)} Approval cannot proceed without a fresh ledger read.</p>}
   {e?.reservation_shortfall&&<p role="alert" className="mt-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">Current holdings are below simulated reservations. ANSH remain transferable on DRUNIX; operator review is required before further simulated disbursement.</p>}
  </>}
  <div className={'mt-5 grid items-start gap-5 '+(role==='INVESTOR'?'xl:grid-cols-[1.05fr_1fr]':'')}>
   {role==='INVESTOR'&&<div className="space-y-5"><Card title="Design your financing request" description="Eligible asset: registered ANSH holdings only. REIT units are excluded.">
    <form className="space-y-4" onSubmit={event=>{event.preventDefault();if(allowed)setReview('apply');}}>
     <SelectField id="finance-asset" label="Collateral asset" value="ANSH" onChange={()=>{}}><option value="ANSH">TechPark One · ANSH economic interests</option></SelectField>
     <div className="grid gap-4 sm:grid-cols-2"><Field id="finance-quantity" label="ANSH to reserve in simulation" type="number" min={1} max={e?.eligible_simulated} step={1} value={quantity} onChange={event=>setQuantity(event.target.value)} required/><Field id="finance-price" label="Illustrative INR value per ANSH" inputMode="decimal" value={price} onChange={event=>setPrice(event.target.value)} required/></div>
     <label className="block text-xs font-semibold text-[#102B4E]" htmlFor="finance-ltv">Illustrative advance rate / LTV <span className="float-right text-[#1769AA]">{ltv}%</span><input id="finance-ltv" className="mt-3 w-full accent-[#1769AA]" type="range" min={20} max={75} step={1} value={ltv} onChange={event=>setLtv(Number(event.target.value))}/></label>
     <div className="grid gap-4 sm:grid-cols-2"><SelectField id="finance-rate" label="Illustrative annual simple rate" value={rate} onChange={event=>setRate(Number(event.target.value))}><option value={800}>8% p.a.</option><option value={1000}>10% p.a.</option><option value={1200}>12% p.a.</option></SelectField><SelectField id="finance-term" label="Fixed repayment term" value={months} onChange={event=>setMonths(Number(event.target.value))}><option value={3}>3 months</option><option value={6}>6 months</option><option value={12}>12 months</option></SelectField></div>
     <p className="text-xs leading-5 text-slate-500">Valuation and rates are illustrative, not an appraisal or bank offer. Full principal plus fixed-term simple interest is repaid together; no partial repayments or compounding.</p>
     {command&&e&&command.quantity>e.eligible_simulated&&<p role="alert" className="text-xs text-amber-800">Requested units exceed eligible simulated collateral.</p>}
     <Button type="submit" disabled={!allowed}>Review financing application <ArrowRight size={15}/></Button>
    </form>
   </Card><Card className="!border-[#102B4E] !bg-[#102B4E] text-white"><div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-blue-200"><Wallet size={17}/> Illustrative liquidity estimate</div><p className="mt-4 font-financial text-3xl font-extrabold">{estimate?moneyINR(estimate.principal_minor):'—'}</p><p className="mt-1 text-xs text-blue-100/75">Estimated loan principal · no real funds</p><dl className="mt-5 space-y-3 text-xs"><div className="flex justify-between gap-3"><dt>Illustrative collateral value</dt><dd>{estimate?moneyINR(estimate.collateral_value_minor):'—'}</dd></div><div className="flex justify-between gap-3"><dt>Fixed-term simple interest</dt><dd>{estimate?moneyINR(estimate.interest_minor):'—'}</dd></div><div className="flex justify-between gap-3 border-t border-white/20 pt-3"><dt>Estimated full repayment</dt><dd className="font-bold">{estimate?moneyINR(estimate.repayment_minor):'—'}</dd></div></dl></Card></div>}
   <div className="space-y-5"><Card title="Financing applications" description="Saved simulation records · no ledger transaction IDs" action={<Landmark size={19} className="text-[#1769AA]"/>}>
    {loans.isPending?<p className="text-sm text-slate-500">Loading saved applications…</p>:loans.error?<p role="alert" className="text-sm text-red-700">{errorFeedback(loans.error)}</p>:loans.data?.length?<div className="space-y-2">{loans.data.map(loan=><button key={loan.id} className={'flex w-full items-center justify-between gap-3 rounded-lg border p-3 text-left '+(current?.id===loan.id?'border-blue-300 bg-blue-50':'border-slate-200 hover:bg-slate-50')} onClick={()=>setSelected(loan.id)}><span><strong className="block text-sm text-[#102B4E]">{moneyINR(loan.principal_minor)} · {loan.quantity} ANSH</strong><span className="mt-1 block text-xs text-slate-500">{labels[loan.state]} · simulated</span></span><Clock3 size={16} className="shrink-0 text-[#1769AA]"/></button>)}</div>:<div className="rounded-lg border border-dashed border-slate-300 p-6 text-center"><Landmark size={25} className="mx-auto text-[#1769AA]"/><p className="mt-3 text-sm font-semibold text-[#102B4E]">Your liquidity journey starts here</p><p className="mt-2 text-xs text-slate-500">Submit an ANSH financing application to preview assessment, reservation, disbursement and repayment.</p></div>}
   </Card>{current&&<Card title="Decision & lifecycle" description="Simulation actions never lock or transfer ANSH"><LoanDetails loan={current} onAction={value=>setReview(value)} busy={mutation.isPending} canRepay={role==='INVESTOR'}/></Card>}
   {mutation.error&&<p role="alert" className="text-sm text-red-700">{errorFeedback(mutation.error)} Refresh saved applications before repeating a simulation action.</p>}
   </div>
  </div>
  <ReviewDialog key={(current?.id||'new')+':'+review} open={review!==null} onOpenChange={value=>{if(!value)setReview(null);}} title={reviewLabels[review||'apply']||'Review simulation'} description="This changes saved application-state simulation only. No legal pledge, bank payment or blockchain lock is created." onConfirm={confirm} busy={mutation.isPending} confirmLabel={reviewLabels[review||'apply']}>
   {review==='apply'&&command&&estimate?<dl><DataRow label="Eligible ANSH" value={command.quantity+' units'}/><DataRow label="Illustrative principal" value={moneyINR(estimate.principal_minor)}/><DataRow label="Full repayment estimate" value={moneyINR(estimate.repayment_minor)}/><DataRow label="LTV / term" value={ltv+'% · '+months+' months'}/></dl>:current?<dl><DataRow label="Application" value={current.id}/><DataRow label="Simulation reservation" value={current.quantity+' ANSH'}/><DataRow label="Illustrative principal" value={moneyINR(current.principal_minor)}/><DataRow label="Repayment amount" value={moneyINR(current.repayment_minor)}/></dl>:null}
  </ReviewDialog>
  {current&&['REJECTED','RELEASED'].includes(current.state)&&<div className="mt-5"><Button variant="secondary" onClick={()=>{newApplication();setSelected(null);}}>Prepare another financing application</Button></div>}
 </>;
}
