import {useEffect,useRef,useState} from 'react';
import {CheckCircle2,Clock3,RefreshCw,Wallet} from 'lucide-react';
import {useApp} from '../app/context';
import {useInvestor} from '../app/investor';
import {request} from '../api/transport';
import {investorDemo} from '../api/transfers';
import {captureIncomeSnapshot} from '../api/income';
import {errorFeedback} from '../api/client';
import {moneyINR,rupeesToMinor} from '../api/financing';
import {entitlement,incomeSnapshot,readPayouts,recordPayout,reitHoldings,reitTotals} from '../demo/investments';
import type {IncomeSnapshot,SimulatedPayout} from '../demo/investments';
import {Card,Metric,SectionHeading} from './ui/card';
import {Button} from './ui/button';
import {DataRow,Field,SelectField} from './ui/form';
import {ReviewDialog} from './ui/dialog';

export function CurrentDistributions(){
 const {mode,preview,session}=useApp(),{balances,portfolio}=useInvestor();
 const holdings=portfolio.data?.items.filter(item=>item.observation_status==='AVAILABLE'&&item.owned_units!==null&&item.owned_units>0)||[];
 const [selectedPropertyId,setSelectedPropertyId]=useState('');
 useEffect(()=>{if(!selectedPropertyId&&holdings[0])setSelectedPropertyId(holdings[0].property_id);},[holdings,selectedPropertyId]);
 const selected=holdings.find(item=>item.property_id===selectedPropertyId)||holdings[0];
 const propertyId=selected?.property_id||investorDemo.property;
 const propertyName=selected?.name||'TechPark One';
 const source=mode==='real'?'DRUNIX_CURRENT_BALANCE':'UI_PREVIEW';
 const refreshBalances=balances.refetch;
 useEffect(()=>{if(mode==='real')void refreshBalances();},[mode,refreshBalances]);
 const units=mode==='real'?selected?.owned_units??undefined:preview?.holding.owned;
 const [rate,setRate]=useState('100.00'),[draft,setDraft]=useState<IncomeSnapshot|null>(null),[reading,setReading]=useState(false),[error,setError]=useState<string|null>(null);
 const pending=useRef(false);
 const [history,setHistory]=useState<{rows:SimulatedPayout[];error:string|null}>(()=>{
  if(typeof window==='undefined')return {rows:[],error:null};
  try{return {rows:readPayouts(window.localStorage,session?.user_id||'preview-investor',propertyId,source),error:null};}
  catch{return {rows:[],error:'Browser simulation history is unavailable or inconsistent; existing records were not overwritten.'};}
 });
 const reit=reitTotals();let rateMinor:string|null=null,ansh:string|null=null;
 try{rateMinor=rupeesToMinor(rate);if(units!==undefined)ansh=entitlement(units,rateMinor);}catch{/* Incomplete rate has no calculated entitlement. */}
 async function review(){
  if(pending.current||rateMinor===null||units===undefined)return;
  pending.current=true;setReading(true);setError(null);
  try{
   // Re-read specifically for the reviewed snapshot; never use a scenario fallback.
   const id=crypto.randomUUID();
   setDraft(mode==='real'?await captureIncomeSnapshot(request,session?.user_id||'',rateMinor,id,()=>new Date().toISOString(),propertyId):incomeSnapshot(id,session?.user_id||'preview-investor',propertyId,units,rateMinor,new Date().toISOString(),source));
   if(mode==='real')void refreshBalances();
  }catch(e){setError(errorFeedback(e));}finally{pending.current=false;setReading(false);}
 }
 function complete(){
  if(!draft)return;
  try{const rows=recordPayout(window.localStorage,draft,new Date().toISOString());setHistory({rows,error:null});setDraft(null);}
  catch{throw new Error('Browser simulation history could not be saved. No payment was executed.');}
 }
 return <><SectionHeading title="Income Distributions" description="Quarterly income illustrations, with ANSH and REIT estimates shown separately." action={<Button variant="secondary" disabled={balances.isFetching||reading} onClick={()=>{void balances.refetch();}}><RefreshCw size={14} className={balances.isFetching?'animate-spin':''}/> Refresh ownership</Button>}/>
  <div className="grid gap-4 md:grid-cols-3"><Metric label="Projected ANSH income" value={ansh===null?'—':moneyINR(ansh)} description="Current-balance illustration · not declared rent"/><Metric label="Projected REIT income" value={moneyINR(reit.quarterly_income_minor)} description="Simulated holdings · illustrative quarterly rates"/><Metric label="Combined quarterly illustration" value={ansh===null?'—':moneyINR(String(BigInt(ansh)+BigInt(reit.quarterly_income_minor)))} description="Income estimates only · not a portfolio valuation"/></div>
  <div className="mt-5 grid items-start gap-5 xl:grid-cols-[.85fr_1.15fr]"><Card title="ANSH entitlement illustration" description="Current-balance observation · illustrative rate"><div className="mb-5 flex items-center gap-3 rounded-lg bg-blue-50 p-4"><Wallet className="text-[#1769AA]" size={22}/><div><p className="text-sm font-bold text-[#102B4E]">{propertyName} · ANSH</p><p className="mt-1 text-xs text-slate-500 break-all">{propertyId}</p><p className="mt-1 text-xs text-slate-600">{units===undefined?'Ownership unavailable':units+' eligible units in this illustration'}</p></div></div>
   {holdings.length>0&&<SelectField id="income-property" label="Property position" value={selected?.property_id||''} onChange={e=>setSelectedPropertyId(e.target.value)} disabled={reading}>{holdings.map(item=><option key={item.property_id} value={item.property_id}>{item.name} · {item.ansh_id}</option>)}</SelectField>}<Field id="income-per-ansh" label="Illustrative quarterly INR amount / ANSH" inputMode="decimal" value={rate} onChange={e=>setRate(e.target.value)} disabled={reading}/>
   <dl className="mt-4"><DataRow label="Ownership source" value={mode==='real'?'DRUNIX current balance via FastAPI':'UI preview scenario'}/><DataRow label="Observation received" value={mode==='real'&&selected?.observed_at?new Date(selected.observed_at).toLocaleString():'Not available'}/><DataRow label="Per-unit illustration" value={rateMinor===null?'Enter a valid INR amount':moneyINR(rateMinor)}/><DataRow label="Estimated entitlement" value={ansh===null?'Unavailable':moneyINR(ansh)}/><DataRow label="Payout state" value="PROJECTED · not executed"/></dl>
   <p className="mt-4 rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-900">This uses a current-balance snapshot, not audited historical or record-date ownership. No on-chain settlement or real cash payout is performed.</p>
   <Button className="mt-4" disabled={rateMinor===null||units===undefined||reading||!!history.error} onClick={()=>{void review();}}>{reading?'Reading current ownership…':'Review simulated payout'}</Button>
   {(error||balances.error)&&<p role="alert" className="mt-3 text-sm text-red-700">{error||errorFeedback(balances.error)}</p>}
  </Card><Card title="Projected distribution breakdown" description="Illustrative quarter · no audited performance or executed payments"><div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>Asset class / position</th><th className="money">Units</th><th className="money">Rate / unit</th><th className="money">Estimate</th></tr></thead><tbody><tr><td><strong>ANSH · TechPark One</strong><p className="text-xs text-slate-500">Current-balance illustration</p></td><td className="money">{units??'—'}</td><td className="money">{rateMinor?moneyINR(rateMinor):'—'}</td><td className="money">{ansh===null?'—':moneyINR(ansh)}</td></tr>{reitHoldings.map(f=><tr key={f.id}><td><strong>{f.fund_name}</strong><p className="text-xs text-slate-500">REIT · simulated representation</p></td><td className="money">{f.units}</td><td className="money">{moneyINR(f.quarterly_distribution_minor)}</td><td className="money">{moneyINR(entitlement(f.units,f.quarterly_distribution_minor))}</td></tr>)}</tbody></table></div><p className="mt-4 text-xs leading-5 text-slate-500">ANSH rent and REIT distributions are different income sources. This rate model is independent of the research valuation assumptions and is not a forecast.</p></Card></div>
  <Card className="mt-5" title="Browser simulation history" description="Only explicit user-confirmed simulations appear here; projections above are not payout records" action={<span className="rounded-full bg-slate-100 px-3 py-1 text-[10px] font-bold text-slate-600">LOCAL DEMO ONLY</span>}>
   {history.error?<p role="alert" className="text-sm text-red-700">{history.error}</p>:history.rows.length?<div className="space-y-3">{history.rows.map(row=><details key={row.id} className="rounded-lg border border-slate-200 p-4"><summary className="cursor-pointer text-sm font-semibold text-[#102B4E]"><span className="inline-flex items-center gap-2"><CheckCircle2 size={16} className="text-[#1769AA]"/>{moneyINR(row.total_minor)} · SIMULATED COMPLETED</span><span className="mt-1 block text-xs font-normal text-slate-500">{new Date(row.completed_at).toLocaleString()} · browser-local record</span></summary><dl className="mt-4 text-xs"><DataRow label="Simulation reference" value={<span className="break-all font-mono">{row.id}</span>}/><DataRow label="Current-balance snapshot received" value={new Date(row.observed_at).toLocaleString()}/>{row.lines.map(line=><DataRow key={line.asset_id} label={line.label+' · '+line.units+' units'} value={moneyINR(line.entitlement_minor)}/>)}</dl></details>)}</div>:<div className="rounded-lg border border-dashed border-slate-300 p-7 text-center"><Clock3 size={24} className="mx-auto text-[#1769AA]"/><p className="mt-3 text-sm font-semibold text-[#102B4E]">No simulated completed payouts yet</p><p className="mt-1 text-xs text-slate-500">Review a current snapshot to create a clearly labeled demo record.</p></div>}
   <p className="mt-4 text-xs leading-5 text-slate-500">Local history keeps up to 20 receipts and can be lost when browser data is cleared. It is not an audit ledger, bank statement or historical ownership proof. No cash balance or holdings are credited.</p>
  </Card>
  <ReviewDialog open={!!draft} onOpenChange={open=>{if(!open)setDraft(null);}} title="Review simulated income payout" description="Save an illustrative completion record in this browser only. No payment API or blockchain transaction is called." confirmLabel="Record simulated payout" onConfirm={complete}>
   {draft&&<dl><DataRow label="ANSH units · fresh snapshot" value={draft.lines[0].units.toString()}/><DataRow label="Snapshot received" value={new Date(draft.observed_at).toLocaleString()}/><DataRow label="ANSH illustration" value={moneyINR(draft.lines[0].entitlement_minor)}/><DataRow label="REIT illustration" value={moneyINR(reit.quarterly_income_minor)}/><DataRow label="Total simulated payout" value={moneyINR(draft.total_minor)}/></dl>}
  </ReviewDialog>
 </>;
}
