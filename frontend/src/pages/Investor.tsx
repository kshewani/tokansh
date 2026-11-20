import {useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,ArrowRightLeft,CheckCircle2,Clock3,Landmark,RefreshCw,ShieldCheck,Wallet} from 'lucide-react';
import {useApp} from '../app/context';
import {useInvestor} from '../app/investor';
import {displayState,investorDemo,terminal} from '../api/transfers';
import type {TransferCommand} from '../api/transfers';
import {errorFeedback} from '../api/client';
import {propertyImage,inr} from '../demo/scenario';
import {Card,Metric,SectionHeading} from '../components/ui/card';
import {Button} from '../components/ui/button';
import {DataRow,Field,SelectField} from '../components/ui/form';
import {ReviewDialog} from '../components/ui/dialog';

const names=['Issuer inventory','Investor A · Aarav','Investor B · existing recipient'];
export function LedgerBalances(){
 const {balances,live}=useInvestor();
 return <div className="space-y-3">
  <div className="flex flex-wrap items-center justify-between gap-2"><span className="inline-flex items-center gap-2 text-xs font-bold text-[#1769AA]"><ShieldCheck size={16}/> DRUNIX balance evaluation</span><Button size="sm" variant="secondary" disabled={balances.isFetching} onClick={()=>{void balances.refetch();}}><RefreshCw size={13} className={balances.isFetching?'animate-spin':''}/> Refresh balances</Button></div>
  <div className="grid gap-3 sm:grid-cols-3">{names.map((name,i)=><Metric key={name} label={name} value={live?live[i].quantity.toLocaleString('en-IN')+' ANSH':balances.isFetching?'Loading…':'—'} description={live?'Read from the ledger · no local estimate':'Authoritative balance unavailable'}/>)}</div>
  {balances.error&&<p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{errorFeedback(balances.error)} Refresh reads when the backend is available.</p>}
  {live&&<p className="text-xs text-slate-500">Last read {new Date(balances.dataUpdatedAt).toLocaleTimeString()}. Holdings are economic interests, not legal property title. No pledge workflow is enabled.</p>}
 </div>;
}
export function TransferProgress(){
 const {snapshot,flow}=useInvestor();const [localError,setError]=useState<string|null>(null);
 const a=snapshot.attempt,r=a?.result;
 if(!a&&!snapshot.error)return null;
 const committed=r?.state==='COMMITTED_VALID';
 const label=snapshot.busy?'Processing':r?displayState(r.state):a?.uncertain?'Unknown':'Failed';
 async function observe(reconcile:boolean){setError(null);try{await (reconcile?flow.reconcile():flow.status());}catch(error){setError(errorFeedback(error));}}
 return <Card title="Transaction progress" description="Payment simulation and blockchain commitment are separate outcomes." className="mt-5" action={<span className={'inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-bold '+(committed?'bg-emerald-50 text-emerald-800':'bg-blue-50 text-[#1769AA]')}>{committed?<CheckCircle2 size={14}/>:<Clock3 size={14}/>} {label}</span>}>
  <div role="status" aria-live="polite" className="text-sm leading-6 text-slate-600">{committed?'DRUNIX confirmed a valid commitment. Fresh balances are being requested.':snapshot.busy?'The backend is processing the original request. Do not submit another transaction.':a?.uncertain?'The original request is unresolved. Inspect or reconcile it; never replace it with a new request.':'This attempt did not confirm a transfer. Review the reported outcome.'}</div>
  <ol className="my-5 grid gap-3 sm:grid-cols-3">{[
   ['1','Simulated payment',r?.payment.status==='SUCCESS'?'Simulated success':r?.payment.status==='FAILED'?'Simulated failure':'Awaiting backend observation'],
   ['2','Ledger submission',r?.transaction_id?'Transaction ID recorded; commitment is separate':'Not confirmed'],
   ['3','Commitment',committed?'Confirmed valid':r?.state==='COMMITTED_INVALID'?'Confirmed invalid':'Not confirmed']
  ].map(([n,title,detail])=><li key={n} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><span className="text-xs font-bold text-[#1769AA]">{n} / {title}</span><p className="mt-2 text-xs text-slate-600">{detail}</p></li>)}</ol>
  <dl className="text-xs"><DataRow label="Backend state" value={r?.state||'No confirmed response'}/><DataRow label="Operation ID" value={<span className="break-all font-mono">{a?.operationId||'Not returned — retain request key'}</span>}/><DataRow label="DRUNIX transaction ID" value={<span className="break-all font-mono">{r?.transaction_id||'Not available'}</span>}/><DataRow label="Idempotency key" value={<span className="break-all font-mono">{a?.key||'—'}</span>}/>{r?.commit&&<DataRow label="Commit evidence" value={'Validation code '+r.commit.code+' · block '+r.commit.block_number}/>}</dl>
  {(snapshot.error||localError)&&<p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{localError||snapshot.error}</p>}
  {r&&['PREPARING','PREPARED'].includes(r.state)&&<p className="mt-3 text-xs text-amber-800">Preparation may still be running or interrupted. This UI cannot resume submission; ask the operator to inspect the original operation.</p>}
  {r&&terminal(r.state)&&<p className="mt-3 text-xs text-slate-500">Stored operation evidence. Current ownership is shown by the fresh balance evaluation above.</p>}
  {a?.operationId&&!terminal(r?.state)&&<div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={snapshot.busy||snapshot.blocked} onClick={()=>{void observe(false);}}>Check saved status</Button><Button size="sm" disabled={snapshot.busy||snapshot.blocked} onClick={()=>{void observe(true);}}><RefreshCw size={14}/> Reconcile original operation</Button></div>}
  {a?.uncertain&&!a.operationId&&!snapshot.busy&&<p className="mt-3 text-xs text-amber-800">The response did not include an operation ID. Give the request key to the operator for recovery. Automatic resubmission is disabled.</p>}
 </Card>;
}
function TransferForm({kind}:{kind:'ACQUISITION'|'TRANSFER'}){
 const {role}=useApp(),{snapshot,flow,live}=useInvestor();
 const [quantity,setQuantity]=useState(kind==='ACQUISITION'?'4':'1'),[payment,setPayment]=useState<'SUCCESS'|'FAILED'>('SUCCESS');
 const [review,setReview]=useState(false),[generation,setGeneration]=useState(0),[error,setError]=useState<string|null>(null);
 const source=kind==='ACQUISITION'?investorDemo.issuer:investorDemo.investor;
 const target=kind==='ACQUISITION'?investorDemo.investor:investorDemo.recipient;
 const available=live?.[kind==='ACQUISITION'?0:1].quantity;
 const value=Number(quantity);
 const valid=/^[1-9][0-9]*$/.test(quantity)&&Number.isSafeInteger(value)&&available!==undefined&&value<=available;
 const blocked=role!=='INVESTOR'||snapshot.busy||snapshot.blocked||!!snapshot.attempt;
 const command:TransferCommand={asset_id:investorDemo.property,from_user_id:source,to_user_id:target,quantity:value,kind,payment_outcome:payment};
 function reset(){try{flow.reset();setReview(false);setGeneration(v=>v+1);setError(null);}catch(e){setError(errorFeedback(e));}}
 return <Card title={kind==='ACQUISITION'?'Acquire ANSH':'Transfer ANSH'} description={kind==='ACQUISITION'?'Issuer inventory → Investor A':'Investor A → Investor B · platform-mediated'}>
  <form className="space-y-4" onSubmit={e=>{e.preventDefault();if(valid&&!blocked)setReview(true);}}>
   <div className="flex items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 p-4"><Wallet size={21} className="shrink-0 text-[#1769AA]"/><div><p className="text-sm font-bold text-[#102B4E]">{kind==='ACQUISITION'?'Meera → Aarav':'Aarav → Investor B'}</p><p className="mt-1 text-xs text-slate-600">Available from sender: {available===undefined?'unavailable':available+' ANSH'}</p></div></div>
   <Field id={'ansh-'+kind} label="ANSH quantity" type="number" min={1} max={available} step={1} value={quantity} onChange={e=>setQuantity(e.target.value)} disabled={blocked} required/>
   <SelectField id={'payment-'+kind} label="Simulated payment outcome" value={payment} disabled={blocked} onChange={e=>setPayment(e.target.value as 'SUCCESS'|'FAILED')}><option value="SUCCESS">Simulate success</option><option value="FAILED">Simulate failure · no ledger transfer</option></SelectField>
   <p className="text-xs leading-5 text-slate-500">No real payment or investment price is settled. The platform signs the transfer; there are no investor wallet signatures. Investor B uses the existing recipient UUID, without a separate demo login.</p>
   <details className="text-xs text-slate-500"><summary className="cursor-pointer font-semibold text-[#1769AA]">Account identifiers</summary><p className="mt-2 break-all">From: {source}</p><p className="mt-1 break-all">To: {target}</p></details>
   <Button type="submit" disabled={!valid||blocked}>{kind==='ACQUISITION'?'Review acquisition':'Review transfer'} <ArrowRight size={15}/></Button>
   {role!=='INVESTOR'&&<p className="text-xs text-amber-800">Switch to the existing Investor demo account to initiate this journey.</p>}
   {snapshot.attempt&&!snapshot.attempt.uncertain&&!snapshot.busy&&<Button className="ml-2" type="button" variant="secondary" onClick={reset}>New request</Button>}
   {error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
  </form>
  <ReviewDialog key={generation} open={review} onOpenChange={setReview} title={kind==='ACQUISITION'?'Confirm ANSH acquisition':'Confirm secondary transfer'} description="Confirm the holder movement and simulated payment. Success requires a valid DRUNIX commitment." busy={snapshot.busy} confirmLabel="Confirm request" onConfirm={async()=>{await flow.begin(command);setReview(false);}}>
   <dl><DataRow label="Quantity" value={quantity+' ANSH'}/><DataRow label="Direction" value={kind==='ACQUISITION'?'Issuer → Investor A':'Investor A → Investor B'}/><DataRow label="Payment" value={'SIMULATED · '+payment}/><DataRow label="Ledger" value="DRUNIX · confirmation required"/></dl>
  </ReviewDialog>
 </Card>;
}
export function ConnectedMarketplace(){
 return <><SectionHeading title="ANSH Marketplace" description="Acquire economic interests from issuer inventory. Payment is simulated; ANSH movements are recorded on DRUNIX." action={<Button asChild variant="secondary"><Link to="/portfolio">My portfolio <ArrowRight size={15}/></Link></Button>}/>
  <LedgerBalances/>
  <div className="mt-5 grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
   <Card className="overflow-hidden !p-0"><img className="h-56 w-full object-cover" src={propertyImage} alt="Illustrative commercial office; not a verified property photograph"/><div className="p-5"><span className="text-xs font-bold uppercase tracking-wider text-[#1769AA]">Registered demo asset · DRUNIX</span><h2 className="mt-2 text-2xl font-bold text-[#102B4E]">TechPark One</h2><p className="mt-2 text-sm leading-6 text-slate-500">Synthetic demonstration label and illustrative imagery. The balance cards show actual backend ledger evaluations.</p><p className="mt-4 break-all rounded-lg bg-slate-50 p-3 font-mono text-xs text-slate-600">{investorDemo.property}</p><p className="mt-4 text-xs leading-5 text-slate-500">No verified appraisal, legal title or guaranteed liquidity is represented. Available inventory is read fresh; the initial 10 ANSH is never used as a fallback.</p></div></Card>
   <TransferForm kind="ACQUISITION"/>
  </div><TransferProgress/>
 </>;
}
export function ConnectedPortfolio({dashboard=false}:{dashboard?:boolean}){
 const {role}=useApp();
 if(role!=='INVESTOR')return <><SectionHeading title="Connected workspace" description="Investor acquisition and portfolio are integrated. Other business workflows remain unavailable."/><Card><Button asChild><Link to="/marketplace">View marketplace</Link></Button></Card></>;
 return <><SectionHeading title={dashboard?'Investor Dashboard':'Investor Portfolio'} description="Live DRUNIX ANSH holdings, with simulated investments kept separate." action={<Button asChild variant="secondary"><Link to="/marketplace">Acquire ANSH <ArrowRight size={15}/></Link></Button>}/>
  <LedgerBalances/>
  <div className="mt-5 grid items-start gap-5 xl:grid-cols-2"><TransferForm kind="TRANSFER"/><Card title="ANSH position" description="Connected property · balances evaluated through FastAPI"><div className="flex items-center gap-3 rounded-lg bg-blue-50 p-4"><ShieldCheck className="text-[#1769AA]"/><div><p className="font-bold text-[#102B4E]">TechPark One</p><p className="mt-1 text-xs text-slate-600">Economic interests · holder {investorDemo.investor.slice(-4)}</p></div></div><p className="mt-5 text-sm leading-6 text-slate-600">Ownership changes are displayed after confirmed commitment and a fresh balance read. Cached transaction evidence is kept separate from current holdings.</p><div className="mt-5 flex items-center gap-2 text-xs font-semibold text-[#1769AA]"><ArrowRightLeft size={16}/> Acquire 4, then transfer 1 in the supervised demo</div><p className="mt-2 text-xs text-slate-500">These are suggested quantities, not assumed ledger outcomes.</p></Card></div>
  <TransferProgress/>
  <div className="mt-5 grid gap-5 xl:grid-cols-2"><Card title="Simulated investment values" description="Illustrative analytics · not connected to DRUNIX balances"><div className="flex items-center gap-3 text-[#1769AA]"><Landmark size={20}/><strong className="text-sm">Separate from your ANSH holdings</strong></div><dl className="mt-4"><DataRow label="Scenario property valuation" value={inr('1000000000',true)}/><DataRow label="Scenario price / ANSH" value={inr('10000')}/><DataRow label="Live investment valuation" value="Unavailable"/><DataRow label="Rental entitlement" value="Not integrated"/></dl><p className="mt-3 text-xs text-slate-500">These synthetic values do not price your ledger position or establish distribution eligibility. Full scenario analytics remain available in Preview Mode.</p></Card><Card title="External REIT holdings" description="Simulated external-data domain · separate from ANSH"><div className="rounded-lg border border-slate-200 p-4"><p className="text-sm font-bold text-[#102B4E]">Illustrative Indian REIT</p><p className="mt-2 text-xs text-slate-500">No connected custodian, live valuation or blockchain custody. Not eligible for ANSH collateral.</p><span className="mt-3 inline-block rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">SIMULATED</span></div></Card></div>
 </>;
}
