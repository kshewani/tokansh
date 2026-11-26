import {ReitHoldingsCard} from '../components/ReitHoldings';
import {useEffect,useState} from 'react';
import {Link} from 'react-router-dom';
import {ArrowRight,ArrowRightLeft,CheckCircle2,Clock3,Landmark,RefreshCw,ShieldCheck,Wallet} from 'lucide-react';
import {useApp} from '../app/context';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useInvestor} from '../app/investor';
import {FinancingSummary} from './Financing';
import {displayState,investorDemo,terminal} from '../api/transfers';
import type {TransferCommand} from '../api/transfers';
import {errorFeedback} from '../api/client';
import {idempotency,request} from '../api/transport';
import {parsePropertyPage,propertyTokenId} from '../api/properties';
import {parseOffering,parseOfferings,parsePurchase,parseWalletBalance,priceMinorToRupees,purchaseStorageKey,readPurchaseRecovery,writePurchaseRecovery} from '../api/marketplace';
import {route} from '../api/contracts';
import {propertyImage,inr} from '../demo/scenario';
import {moneyINR} from '../api/financing';
import {Card,Metric,SectionHeading} from '../components/ui/card';
import {Button} from '../components/ui/button';
import {DataRow,Field,SelectField} from '../components/ui/form';
import {ReviewDialog} from '../components/ui/dialog';

export function LedgerBalances(){
 const {session}=useApp(),{balances,live}=useInvestor();
 return <div className="space-y-3">
  <div className="flex flex-wrap items-center justify-between gap-2"><span className="inline-flex items-center gap-2 text-xs font-bold text-[#1769AA]"><ShieldCheck size={16}/> DRUNIX balance evaluation</span><Button size="sm" variant="secondary" disabled={balances.isFetching} onClick={()=>{void balances.refetch();}}><RefreshCw size={13} className={balances.isFetching?'animate-spin':''}/> Refresh balances</Button></div>
  <div className="grid gap-3 sm:grid-cols-2"><Metric label={(session?.display_name||'Investor')+' · personal holdings'} value={live?live.quantity.toLocaleString('en-IN')+' ANSH':balances.isFetching?'Loading…':'—'} description={live?'Read from the ledger · no local estimate':'Authoritative balance unavailable'}/><Metric label="Issuer inventory" value="Protected" description="Not exposed through an investor balance read"/></div>
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
  <details className="text-xs"><summary className="font-semibold text-blue-700">Transaction evidence & identifiers</summary><dl><DataRow label="Backend state" value={r?.state||'No confirmed response'}/><DataRow label="Operation ID" value={<span className="break-all font-mono">{a?.operationId||'Not returned — retain request key'}</span>}/><DataRow label="DRUNIX transaction ID" value={<span className="break-all font-mono">{r?.transaction_id||'Not available'}</span>}/><DataRow label="Idempotency key" value={<span className="break-all font-mono">{a?.key||'—'}</span>}/>{r?.commit&&<DataRow label="Commit evidence" value={'Validation code '+r.commit.code+' · block '+r.commit.block_number}/>}</dl></details>
  {(snapshot.error||localError)&&<p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">{localError||snapshot.error}</p>}
  {r&&['PREPARING','PREPARED'].includes(r.state)&&<p className="mt-3 text-xs text-amber-800">Preparation may still be running or interrupted. This UI cannot resume submission; ask the operator to inspect the original operation.</p>}
  {r&&terminal(r.state)&&<p className="mt-3 text-xs text-slate-500">Stored operation evidence. Current ownership is shown by the fresh balance evaluation above.</p>}
  {a?.operationId&&!terminal(r?.state)&&<div className="mt-4 flex flex-wrap gap-2"><Button size="sm" variant="secondary" disabled={snapshot.busy||snapshot.blocked} onClick={()=>{void observe(false);}}>Check saved status</Button><Button size="sm" disabled={snapshot.busy||snapshot.blocked} onClick={()=>{void observe(true);}}><RefreshCw size={14}/> Reconcile original operation</Button></div>}
  {a?.uncertain&&!a.operationId&&!snapshot.busy&&<p className="mt-3 text-xs text-amber-800">The response did not include an operation ID. Give the request key to the operator for recovery. Automatic resubmission is disabled.</p>}
 </Card>;
}
function TransferForm({kind}:{kind:'ACQUISITION'|'TRANSFER'}){
 const {role,session}=useApp(),{snapshot,flow,live,portfolio}=useInvestor();
 const properties=portfolio.data?.items.filter(item=>item.observation_status==='AVAILABLE'&&item.owned_units!==null)||[];
 const [propertyId,setPropertyId]=useState('');
 useEffect(()=>{if(!propertyId&&properties[0])setPropertyId(properties[0].property_id);},[properties,propertyId]);
 const property=properties.find(item=>item.property_id===propertyId);
 const [quantity,setQuantity]=useState(kind==='ACQUISITION'?'4':'1'),[payment,setPayment]=useState<'SUCCESS'|'FAILED'>('SUCCESS');
 const [review,setReview]=useState(false),[generation,setGeneration]=useState(0),[error,setError]=useState<string|null>(null);
 const source=kind==='ACQUISITION'?property?.issuer_id||'':session?.user_id||'';
 const target=kind==='ACQUISITION'?session?.user_id||'':investorDemo.recipient;
 const available=kind==='ACQUISITION'?undefined:(property?.transferable_units??live?.quantity);
 const value=Number(quantity);
 const valid=/^[1-9][0-9]*$/.test(quantity)&&Number.isSafeInteger(value)&&(kind==='ACQUISITION'||(available!==undefined&&value<=available))&&!!session?.user_id;
 const blocked=role!=='INVESTOR'||snapshot.busy||snapshot.blocked||!!snapshot.attempt||!propertyId;
 const command:TransferCommand={asset_id:propertyId,from_user_id:source,to_user_id:target,quantity:value,kind,payment_outcome:payment};
 function reset(){try{flow.reset();setReview(false);setGeneration(v=>v+1);setError(null);}catch(e){setError(errorFeedback(e));}}
 return <Card title={kind==='ACQUISITION'?'Acquire ANSH':'Transfer ANSH'} description={kind==='ACQUISITION'?'Issuer inventory → your authenticated investor account':'Your authenticated investor account → existing recipient · platform-mediated'}>
  <form className="space-y-4" onSubmit={e=>{e.preventDefault();if(valid&&!blocked)setReview(true);}}>
   <div className="flex items-center gap-3 rounded-lg border border-blue-100 bg-blue-50 p-4"><Wallet size={21} className="shrink-0 text-[#1769AA]"/><div><p className="text-sm font-bold text-[#102B4E]">{kind==='ACQUISITION'?'Property issuer → '+(session?.display_name||'investor'):(session?.display_name||'Investor')+' → existing recipient'}</p><p className="mt-1 text-xs text-slate-600">{property?property.name+' · '+propertyTokenId(property.property_id):'Select an observed property'} · available from sender: {available===undefined?'Validated by backend':available+' ANSH'}</p></div></div>
   <SelectField id={'transfer-property-'+kind} label="Property position" value={propertyId} disabled={blocked} onChange={e=>setPropertyId(e.target.value)}>{properties.map(item=><option key={item.property_id} value={item.property_id}>{item.name} · {propertyTokenId(item.property_id)}</option>)}</SelectField>
   <Field id={'ansh-'+kind} label="ANSH quantity" type="number" min={1} max={available} step={1} value={quantity} onChange={e=>setQuantity(e.target.value)} disabled={blocked} required/>
   <SelectField id={'payment-'+kind} label="Simulated payment outcome" value={payment} disabled={blocked} onChange={e=>setPayment(e.target.value as 'SUCCESS'|'FAILED')}><option value="SUCCESS">Simulate success</option><option value="FAILED">Simulate failure · no ledger transfer</option></SelectField>
   <p className="text-xs leading-5 text-slate-500">No real payment or investment price is settled. The platform signs the transfer; there are no investor wallet signatures. The backend validates the authenticated sender and recipient permissions.</p>
   <details className="text-xs text-slate-500"><summary className="cursor-pointer font-semibold text-[#1769AA]">Account identifiers</summary><p className="mt-2 break-all">From: {source}</p><p className="mt-1 break-all">To: {target}</p></details>
   <Button type="submit" disabled={!valid||blocked}>{kind==='ACQUISITION'?'Review acquisition':'Review transfer'} <ArrowRight size={15}/></Button>
   {role!=='INVESTOR'&&<p className="text-xs text-amber-800">Switch to the existing Investor demo account to initiate this journey.</p>}
   {snapshot.attempt&&!snapshot.attempt.uncertain&&!snapshot.busy&&<Button className="ml-2" type="button" variant="secondary" onClick={reset}>New request</Button>}
   {error&&<p role="alert" className="text-sm text-red-700">{error}</p>}
  </form>
  <ReviewDialog key={generation} open={review} onOpenChange={setReview} title={kind==='ACQUISITION'?'Confirm ANSH acquisition':'Confirm secondary transfer'} description="Confirm the holder movement and simulated payment. Success requires a valid DRUNIX commitment." busy={snapshot.busy} confirmLabel="Confirm request" onConfirm={async()=>{await flow.begin(command);setReview(false);}}>
   <dl><DataRow label="Quantity" value={quantity+' ANSH'}/><DataRow label="Direction" value={kind==='ACQUISITION'?'Issuer → '+(session?.display_name||'authenticated investor'):(session?.display_name||'Authenticated investor')+' → existing recipient'}/><DataRow label="Payment" value={'SIMULATED · '+payment}/><DataRow label="Ledger" value="DRUNIX · confirmation required"/></dl>
  </ReviewDialog>
 </Card>;
}
export function ConnectedMarketplace(){
 const {session}=useApp();
 const queryClient=useQueryClient();
 const [selectedId,setSelectedId]=useState('');
 const [quantity,setQuantity]=useState('1');
 const [error,setError]=useState('');
 const [purchase,setPurchase]=useState<ReturnType<typeof parsePurchase>|null>(null);
 const offerings=useQuery({queryKey:['marketplace-offerings'],queryFn:async()=>parseOfferings(await request<unknown>(route.offerings))});
 const properties=useQuery({queryKey:['marketplace-properties'],queryFn:async()=>parsePropertyPage(await request<unknown>(route.properties))});
 const wallet=useQuery({queryKey:['demo-wallet',session?.user_id],enabled:Boolean(session),queryFn:async()=>parseWalletBalance(await request<unknown>(route.wallet),session!.user_id)});
 const selected=offerings.data?.find(value=>value.id===selectedId)||offerings.data?.[0];
 const property=properties.data?.find(value=>value.id===selected?.property_id);
 const selfOffering=Boolean(selected&&session&&selected.issuer_id===session.user_id);
 useEffect(()=>{if(!selectedId&&offerings.data?.[0])setSelectedId(offerings.data[0].id);},[offerings.data,selectedId]);
 useEffect(()=>{if(!selected||!session)return;const saved=typeof window==='undefined'?null:readPurchaseRecovery(window.sessionStorage,purchaseStorageKey(session.user_id,selected.id));if(saved?.result)setPurchase(saved.result);},[selected,session]);
 const begin=useMutation({mutationFn:async()=>{
   if(!selected||selfOffering)throw new Error('Select an offering available to this investor.');
   const value=Number(quantity);if(!Number.isSafeInteger(value)||value<1||value>selected.available_quantity)throw new Error('Enter a quantity within the available offering inventory.');
   const key=typeof window==='undefined'?idempotency():readPurchaseRecovery(window.sessionStorage,purchaseStorageKey(session!.user_id,selected.id))?.key||idempotency();
   const storageKey=purchaseStorageKey(session!.user_id,selected.id);if(typeof window!=='undefined')writePurchaseRecovery(window.sessionStorage,storageKey,{key});
   const result=parsePurchase(await request<unknown>(route.purchases,{method:'POST',body:{offering_id:selected.id,quantity:value},idempotencyKey:key,correlationId:key}));
   if(typeof window!=='undefined')writePurchaseRecovery(window.sessionStorage,storageKey,{key,operationId:result.operation_id,result});
   return result;
  },onSuccess:result=>{setPurchase(result);setError('');void queryClient.invalidateQueries({queryKey:['marketplace-offerings']});void queryClient.invalidateQueries({queryKey:['demo-wallet',session?.user_id]});void queryClient.invalidateQueries({queryKey:['investor-balances',session?.user_id]});},onError:value=>setError(errorFeedback(value))});
 const reconcile=useMutation({mutationFn:async()=>{if(!purchase)throw new Error('No purchase operation to reconcile.');return parsePurchase(await request<unknown>(route.purchases+'/'+purchase.operation_id+'/reconcile',{method:'POST',correlationId:purchase.operation_id}));},onSuccess:result=>{setPurchase(result);setError('');void queryClient.invalidateQueries({queryKey:['marketplace-offerings']});void queryClient.invalidateQueries({queryKey:['demo-wallet',session?.user_id]});void queryClient.invalidateQueries({queryKey:['investor-balances',session?.user_id]});},onError:value=>setError(errorFeedback(value))});
 const terminal=purchase&&['SETTLED','FAILED','COMMITTED_INVALID'].includes(purchase.state);
 let total='0';try{if(/^[0-9]+$/.test(quantity)&&selected)total=String(BigInt(selected.price_minor)*BigInt(quantity));}catch{/* Keep invalid input at zero until corrected. */}
 return <><SectionHeading title="ANSH Marketplace" description="Purchase existing issuer inventory. Cash is simulated; ownership changes only after confirmed DRUNIX transfer." action={<Button asChild variant="secondary"><Link to="/portfolio">My portfolio <ArrowRight size={15}/></Link></Button>}/>
  <div className="mt-5 grid items-start gap-5 xl:grid-cols-[1.05fr_1fr]">
   <Card className="overflow-hidden !p-0"><img className="h-56 w-full object-cover" src={propertyImage} alt="Illustrative commercial office; not a verified property photograph"/><div className="p-5"><span className="text-xs font-bold uppercase tracking-wider text-[#1769AA]">Issuer inventory · DRUNIX settlement</span><h2 className="mt-2 text-2xl font-bold text-[#102B4E]">{property?.name||'Available ANSH offerings'}</h2><p className="mt-2 text-sm leading-6 text-slate-500">Offering inventory and purchase state are read from the backend. No purchase mints ANSH.</p><p className="mt-4 text-xs leading-5 text-slate-500">Canonical ANSH identity: {selected?propertyTokenId(selected.property_id):'Select an offering'}</p></div></Card>
   <Card title="Purchase ANSH" description="The backend derives seller, property, price and total cost from the offering.">
    {offerings.isLoading&&<p className="text-sm text-slate-500">Loading active offerings…</p>}{offerings.error&&<p role="alert" className="text-sm text-red-700">{errorFeedback(offerings.error)}</p>}{!offerings.isLoading&&!offerings.error&&!selected&&<p className="text-sm text-slate-500">No active offerings are currently available.</p>}
    {selected&&!offerings.error&&<form className="space-y-4" onSubmit={e=>{e.preventDefault();if(!purchase&&!begin.isPending&&!selfOffering)begin.mutate();}}><SelectField id="market-offering" label="Property offering" value={selected.id} onChange={e=>{setSelectedId(e.target.value);setPurchase(null);}}>{offerings.data?.map(value=><option key={value.id} value={value.id}>{properties.data?.find(p=>p.id===value.property_id)?.name||value.property_id} · {value.available_quantity} ANSH{session&&value.issuer_id===session.user_id?' · Your offering':''}</option>)}</SelectField><DataRow label="ANSH identity" value={propertyTokenId(selected.property_id)}/><DataRow label="Price / ANSH" value={priceMinorToRupees(selected.price_minor)}/><DataRow label="Available quantity" value={selected.available_quantity+' ANSH'}/><DataRow label="Issuer" value={selected.issuer_id}/>{selfOffering&&<p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">This is your offering. Self-purchase is unavailable.</p>}<Field id="market-quantity" label="Purchase quantity" type="number" min={1} max={selected.available_quantity} step={1} value={quantity} onChange={e=>setQuantity(e.target.value)} disabled={Boolean(purchase)||begin.isPending||selfOffering}/><DataRow label="Total purchase cost" value={priceMinorToRupees(total)}/><DataRow label="Available simulated cash" value={wallet.data?priceMinorToRupees(wallet.data.available_minor):wallet.isFetching?'Loading…':'Unavailable'}/>{error&&<p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}<Button type="submit" disabled={Boolean(purchase)||begin.isPending||!wallet.data||selfOffering}>{begin.isPending?'Submitting…':'Purchase existing ANSH'}</Button></form>}
   </Card>
  </div>
  {purchase&&<Card className="mt-5" title="Purchase status" description="Ownership and proceeds are displayed only after local settlement follows confirmed DRUNIX commitment."><dl><DataRow label="State" value={purchase.state}/><DataRow label="Operation" value={<span className="break-all font-mono">{purchase.operation_id}</span>}/><DataRow label="Transaction" value={purchase.transaction_id||'Not confirmed'}/><DataRow label="Quantity" value={purchase.quantity+' ANSH'}/><DataRow label="Total" value={priceMinorToRupees(purchase.total_amount_minor)}/></dl>{['UNKNOWN','SUBMITTED','SUBMISSION_PENDING','COMMITTED_PENDING_SETTLEMENT','RECONCILIATION_REQUIRED'].includes(purchase.state)&&<Button className="mt-4" variant="secondary" disabled={reconcile.isPending} onClick={()=>reconcile.mutate()}>{reconcile.isPending?'Reconciling…':'Reconcile purchase'}</Button>}{terminal&&<Button className="mt-4 ml-2" variant="secondary" onClick={()=>setPurchase(null)}>New purchase</Button>}</Card>}
 </>;
}
export function ConnectedPortfolio({dashboard=false}:{dashboard?:boolean}){
 const {role,session}=useApp(),{portfolio}=useInvestor();
 if(role!=='INVESTOR')return <><SectionHeading title="Connected workspace" description="Investor acquisition and portfolio are integrated. Other business workflows remain unavailable."/><Card><Button asChild><Link to="/marketplace">View marketplace</Link></Button></Card></>;
 if(portfolio.isPending)return <><SectionHeading title={dashboard?'Investor Dashboard':'Investor Portfolio'} description="Reading property-specific DRUNIX holdings."/><Card><p className="text-sm text-slate-500">Loading authenticated portfolio observations…</p></Card></>;
 if(portfolio.error)return <><SectionHeading title="Investor Portfolio" description="Live property-specific holdings, with unavailable observations kept separate."/><Card><p role="alert" className="text-sm text-red-700">{errorFeedback(portfolio.error)}</p></Card></>;
 const data=portfolio.data!,observed=data.items.filter(item=>item.observation_status==='AVAILABLE'&&item.owned_units!==null&&item.issued_supply!==null);
 const held=observed.filter(item=>item.owned_units!>0),total=data.aggregate.total_indicative_value_minor;
 const ownership=(owned:number,issued:number)=>{const basis=BigInt(owned)*10000n/BigInt(issued);return `${basis/100n}.${(basis%100n).toString().padStart(2,'0')}%`;};
 return <><SectionHeading title={dashboard?'Investor Dashboard':'Investor Portfolio'} description="Property-specific DRUNIX holdings. Indicative values use each property's initial issue price." action={<Button asChild variant="secondary"><Link to="/marketplace">Acquire ANSH <ArrowRight size={15}/></Link></Button>}/>
  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Indicative ANSH value" value={total===null?'Unavailable':moneyINR(total)} description={data.aggregate.status==='COMPLETE'?'Initial issue price basis':'Partial observation'}/><Metric label="Properties held" value={String(held.length)} description="Distinct property positions"/><Metric label="Observed positions" value={String(observed.length)} description="DRUNIX balance observations"/><Metric label="REIT value" value="Separate" description="Simulated asset class · not ANSH"/></div>
  {data.aggregate.status!=='COMPLETE'&&<p role="status" className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Some property observations are unavailable. No unavailable balance is treated as zero and aggregate value is not presented as complete.</p>}
  <Card className="mt-5" title="Property-specific holdings" description="Each row is a separate ANSH balance; quantities are not interchangeable across properties.">
   {held.length===0?<p className="text-sm text-slate-500">No confirmed property holdings are available for this investor.</p>:<div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>Property</th><th>ANSH identity</th><th className="money">Held</th><th className="money">Issued</th><th className="money">Ownership</th><th className="money">Indicative value</th><th>Actions</th></tr></thead><tbody>{held.map(item=><tr key={item.property_id}><td><strong>{item.name}</strong><span className="block text-xs text-slate-500">{item.category} · {item.location}</span></td><td className="font-mono text-xs break-all">{propertyTokenId(item.property_id)}</td><td className="money">{item.owned_units!.toLocaleString('en-IN')}</td><td className="money">{item.issued_supply!.toLocaleString('en-IN')}</td><td className="money">{ownership(item.owned_units!,item.issued_supply!)}</td><td className="money">{moneyINR(String(BigInt(item.owned_units!)*BigInt(item.initial_issue_price_minor)))}<span className="block text-[10px] text-slate-500">Initial issue price</span></td><td><div className="flex flex-wrap gap-2"><Button asChild size="sm" variant="ghost"><Link to={`/intelligence?property=${encodeURIComponent(item.property_id)}`}>Research</Link></Button><Button asChild size="sm" variant="ghost"><Link to={`/collateral?property=${encodeURIComponent(item.property_id)}`}>Finance</Link></Button><Button asChild size="sm" variant="ghost"><Link to={`/distributions?property=${encodeURIComponent(item.property_id)}`}>Income</Link></Button></div></td></tr>)}</tbody></table></div>}
   <p className="mt-4 text-xs text-slate-500">Indicative value at initial issue price. This is not a live market price, return, legal title or payout evidence.</p>
  </Card>
  <div className="mt-5 grid gap-5 xl:grid-cols-2"><FinancingSummary/><ReitHoldingsCard/></div>
 </>;
}
