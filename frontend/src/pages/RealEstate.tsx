import {useEffect,useRef,useState} from 'react';
import {ArrowRight,Building2,FileCheck2,FileClock,Info,MapPin,ShieldAlert} from 'lucide-react';
import {useApp,usePreview} from '../app/context';
import {ConnectedMarketplace} from './Investor';
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {route} from '../api/contracts';
import type {NewIssuance,NewOrder,NewProperty} from '../api/contracts';
import {errorFeedback} from '../api/client';
import {idempotency,request} from '../api/transport';
import {DEFAULT_INITIAL_PRICE_MINOR,deriveSupply,parseBalanceQuantity,parseIssuance,parseProperty,parsePropertyIssuanceState,parsePropertyPage,propertyTokenId,readIssuanceRecovery,rupeesToMinor,writeIssuanceRecovery} from '../api/properties';
import {phaseIndex,integer,inr,propertyImage,sample} from '../demo/scenario';
import {Button} from '../components/ui/button';
import {Card,Metric,SectionHeading} from '../components/ui/card';
import {ReviewDialog} from '../components/ui/dialog';
import {Field,SelectField,DataRow} from '../components/ui/form';
import {PreviewWarning,Status} from '../components/ui/status';
function TransitionTimeline({phase}:{phase:string}){
 const labels=['Order created','Business validation','Simulated payment','DRUNIX submission','Ledger commitment','Portfolio projection'];
 return <ol className="space-y-4">{labels.map((label,i)=><li key={label} className="flex items-start gap-3"><span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-[#1769AA]">{i+1}</span><div><p className="text-sm font-semibold text-slate-700">{label}</p><p className="mt-1 text-xs text-slate-500">{i<3?'Supporting workflow stage':i===3?'Submission requires Python and DRUNIX':i===4?'Only actual commit permits success':'Only refresh after verified commit'}</p></div><Status value={i===0&&phase==='PURCHASED'?'PREVIEW_ONLY':'UNAVAILABLE'}/></li>)}</ol>;
}
export function Registry(){
 const {mode}=useApp();
 return mode==='real'?<ConnectedRegistry/>:<PreviewRegistry/>;
}
function ConnectedRegistry(){
 const {session}=useApp();
 const queryClient=useQueryClient();
 const [name,setName]=useState(sample.name),[location,setLocation]=useState(sample.location);
 const [category,setCategory]=useState('Commercial office'),[valuation,setValuation]=useState('10000000');
 const [error,setError]=useState('');
 const supply=deriveSupply(valuation,DEFAULT_INITIAL_PRICE_MINOR);
 const key=useRef(idempotency());
 const properties=useQuery({queryKey:['issuer-properties',session?.user_id],enabled:Boolean(session),queryFn:async()=>parsePropertyPage(await request<unknown>(route.properties))});
 const create=useMutation({mutationFn:async()=>{
   const payload:NewProperty={name,location,category,valuation,proposed_supply:supply!,currency:'INR'};
   return parseProperty(await request<unknown>(route.properties,{method:'POST',body:payload,idempotencyKey:key.current,correlationId:key.current}));
  },onSuccess:()=>{setError('');key.current=idempotency();void queryClient.invalidateQueries({queryKey:['issuer-properties',session?.user_id]});},onError:value=>setError(errorFeedback(value))});
 const valid=name.trim().length>2&&location.trim().length>2&&supply!==null;
 return <><SectionHeading title="Property Registry" description="Create an application as the authenticated investor. Approval and DRUNIX registration remain separate backend workflows."/>
  <div className="grid gap-4 lg:grid-cols-3"><Metric label="Authenticated issuer" value={session?.display_name||'Unavailable'} description="Issuer identity comes from the bearer session"/><Metric label="Initial issue price" value="₹1,000" description="Backend-configured default"/><Metric label="Calculated ANSH supply" value={supply===null?'Invalid':integer(supply)} description="Approved value ÷ issue price"/></div>
  <div className="mt-5 grid gap-5 xl:grid-cols-[1.15fr_1fr]">
   <Card title="Property information" description="New applications use your authenticated investor UUID as issuer_id">
    <form onSubmit={e=>{e.preventDefault();if(valid)create.mutate();}} className="grid gap-4 sm:grid-cols-2">
     <Field label="Property name" id="connected-reg-name" value={name} onChange={e=>setName(e.target.value)} required minLength={3}/><Field label="Location" id="connected-reg-location" value={location} onChange={e=>setLocation(e.target.value)} required/>
     <SelectField label="Property category" id="connected-reg-category" value={category} onChange={e=>setCategory(e.target.value)}><option>Commercial office</option><option>Residential</option><option>Industrial</option></SelectField>
     <Field label="Approved tokenized value (INR)" id="connected-reg-value" type="number" min={1} value={valuation} onChange={e=>setValuation(e.target.value)} required/><Field label="Calculated ANSH supply" id="connected-reg-supply" value={supply===null?'Not divisible by ₹1,000':String(supply)} readOnly/>
     <Field label="Initial issue price / ANSH (INR)" id="connected-reg-price" value="1000" readOnly/><Field label="Issuer / owner" id="connected-reg-issuer" value={session?.display_name||''} readOnly/>
     <div className="sm:col-span-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-500">Backend validation is authoritative. Registration, approval and issuance are separate operations.</div>
     {error&&<p className="sm:col-span-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}
     <div className="sm:col-span-2"><Button type="submit" disabled={!valid||create.isPending}>{create.isPending?'Submitting…':'Create property application'} <ArrowRight size={15}/></Button></div>
    </form>
   </Card>
   <Card title="My properties" description="Only records returned by the authenticated backend session are shown"><div className="space-y-3">{properties.isLoading&&<p className="text-sm text-slate-500">Loading properties…</p>}{properties.error&&<p className="text-sm text-red-700">{errorFeedback(properties.error)}</p>}{properties.data?.filter(value=>value.issuer_id===session?.user_id).map(value=><div key={value.id} className="rounded-lg border border-slate-200 p-3"><div className="flex justify-between gap-3"><strong className="text-sm text-[#102B4E]">{value.name}</strong><Status value={value.ledger_registration_status==='REGISTERED'?'COMMITTED':'DRAFT'}/></div><p className="mt-1 text-xs text-slate-500">{propertyTokenId(value.id)} · {value.valuation} INR · {value.approved_supply||value.proposed_supply} ANSH approved/proposed</p></div>)}{properties.data?.length===0&&<p className="text-sm text-slate-500">No properties registered for this investor.</p>}</div></Card>
  </div></>;
}
function PreviewRegistry(){
 const {property,phase,submit,submitting}=usePreview();
 const [open,setOpen]=useState<'register'|'submit'|'approve'|'reject'|null>(null);
 const [name,setName]=useState(sample.name);const [location,setLocation]=useState(sample.location);
 const [category,setCategory]=useState('Commercial office');const [valuation,setValuation]=useState(sample.valuation);
 const [supply,setSupply]=useState(sample.approvedSupply);const [price,setPrice]=useState(sample.unitPrice);
 const valid=name.trim().length>2&&location.trim().length>2&&Number(valuation)>0&&Number.isSafeInteger(supply)&&supply>0&&Number(price)>0;
 const payload:NewProperty={name,location,category,valuation,proposed_supply:supply,issue_price:price,currency:'INR'};
 async function confirm(){
  if(!open||!valid)return;
  const path=open==='register'?route.properties:route.properties+'/'+sample.id+'/'+(open==='submit'?'submit':open==='approve'?'approve':'reject');
  await submit(path,open==='register'?payload:{reason:open==='reject'?'Needs verification':undefined});
  setOpen(null);
 }
 return <><SectionHeading title="Property Registry" description="Manage onboarding, application-level approval and eligibility for ANSH issuance."/>
 <div className="grid gap-4 lg:grid-cols-3"><Metric label="Registered properties (preview)" value={phaseIndex(phase)>=1?'1':'0'} description="No live application database"/><Metric label="Approval stage" value={property.approval} description="Scenario illustration only"/><Metric label="Approved ANSH supply" value={integer(sample.approvedSupply)} description="Proposed issuance ceiling"/></div>
 <div className="mt-5 grid gap-5 xl:grid-cols-[1.15fr_1fr]">
 <Card title="Property information" description="Synthetic property record; real records require an API request">
 <form onSubmit={e=>{e.preventDefault();if(valid)setOpen('register');}} className="grid gap-4 sm:grid-cols-2">
 <Field label="Property name" id="reg-name" value={name} onChange={e=>setName(e.target.value)} required minLength={3}/>
 <Field label="Property identifier" id="reg-id" value={sample.id} readOnly/>
 <Field label="Location" id="reg-location" value={location} onChange={e=>setLocation(e.target.value)} required/>
 <SelectField label="Property category" id="reg-category" value={category} onChange={e=>setCategory(e.target.value)}><option>Commercial office</option><option>Residential</option><option>Industrial</option></SelectField>
 <Field label="Illustrative valuation (INR)" id="reg-value" type="number" min={1} value={valuation} onChange={e=>setValuation(e.target.value)} required/>
 <Field label="Total proposed ANSH" id="reg-supply" type="number" min={1} step={1} value={supply} onChange={e=>setSupply(Number(e.target.value))} required/>
 <Field label="Issue price / ANSH (INR)" id="reg-price" type="number" min={1} value={price} onChange={e=>setPrice(e.target.value)} required/>
 <Field label="Issuer / owner" id="reg-issuer" value={sample.issuer} readOnly/>
 <div className="sm:col-span-2"><p className="mb-2 text-xs font-semibold text-[#102B4E]">Supporting documents</p><div className="rounded-lg border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-500">No verified title, valuation or approval documents attached. File upload requires the backend document service.</div></div>
 <div className="sm:col-span-2 flex flex-wrap gap-2"><Button type="submit" disabled={!valid||submitting}>Review registration <ArrowRight size={15}/></Button><Button variant="secondary" type="button" onClick={()=>setOpen('submit')}>Submit for approval</Button><Button variant="secondary" type="button" onClick={()=>setOpen('approve')}>Review approval</Button></div>
 </form></Card>
 <Card title="Application and ledger stages" description="Approval alone does not imply DRUNIX asset registration">
 <dl><DataRow label="Application approval" value={<Status value={property.approval}/>}/><DataRow label="Approved property registration" value={<Status value="UNAVAILABLE"/>}/><DataRow label="DRUNIX transaction reference" value="None — backend not connected"/><DataRow label="Issuance eligibility" value={property.approval==='APPROVED'?'Requires ledger registration commitment':'Approval required'}/><DataRow label="Documents verified" value="Not established"/></dl>
 <div className="mt-5 rounded-lg bg-slate-50 p-4 text-xs leading-6 text-slate-600"><strong>Important:</strong> registration and application approval are distinct. After approval, the backend must register the approved asset on DRUNIX before ANSH issuance.</div>
 <div className="mt-4 flex gap-2"><Button variant="secondary" onClick={()=>setOpen('reject')}>Review rejection</Button></div>
 </Card></div>
 <ReviewDialog open={!!open} onOpenChange={v=>!v&&setOpen(null)} title={(open||'Property')+' — review'} description="Confirm the intended request. Preview mode never changes an application or ledger record." onConfirm={confirm} busy={submitting} confirmLabel="Submit to API">
 <dl><DataRow label="Property" value={name}/><DataRow label="Illustrative valuation" value={inr(valuation)}/><DataRow label="Proposed supply" value={integer(supply)}/><DataRow label="Issue price" value={inr(price)}/><DataRow label="Operation" value={open||'—'}/></dl></ReviewDialog>
 </>;
}
export function Issuance(){
 const {mode}=useApp();
 return mode==='real'?<ConnectedIssuance/>:<PreviewIssuance/>;
}
function ConnectedIssuance(){
 const {session}=useApp();
 const queryClient=useQueryClient();
 const [selectedId,setSelectedId]=useState('');
 const [error,setError]=useState('');
 const [operation,setOperation]=useState<ReturnType<typeof parseIssuance>|null>(null);
 const properties=useQuery({queryKey:['issuer-properties',session?.user_id],enabled:Boolean(session),queryFn:async()=>parsePropertyPage(await request<unknown>(route.properties))});
 const own=(properties.data||[]).filter(value=>value.issuer_id===session?.user_id);
 const selected=own.find(value=>value.id===selectedId)||own[0];
 const balance=useQuery({queryKey:['issuer-balance',session?.user_id,selected?.id],enabled:Boolean(session&&selected),queryFn:async()=>parseBalanceQuantity(await request<unknown>(`/api/v1/ansh/balances/${selected!.id}/${session!.user_id}`),selected!.id,session!.user_id)});
 const ledgerState=useQuery({queryKey:['issuer-issuance-state',session?.user_id,selected?.id],enabled:Boolean(session&&selected?.ledger_registration_status==='REGISTERED'),queryFn:async()=>parsePropertyIssuanceState(await request<unknown>(`/api/v1/properties/${selected!.id}/issuance-state`),selected!.id)});
 useEffect(()=>{if(!selectedId&&own[0])setSelectedId(own[0].id);},[own,selectedId]);
 useEffect(()=>{if(!selected||!session)return;const raw=typeof window==='undefined'?null:readIssuanceRecovery(window.sessionStorage,`tokansh-issuance-v1:${session.user_id}:${selected.id}`);if(raw?.result)setOperation(raw.result);},[selected,session]);
 const issue=useMutation({mutationFn:async()=>{
   if(!selected||selected.ledger_registration_status!=='REGISTERED'||selected.approved_supply<=0)throw new Error('Property registration must be committed before issuance.');
   const issuePrice=rupeesToMinor(selected.unit_price);if(!issuePrice)throw new Error('Property issue price is invalid.');
   const key=typeof window==='undefined'?idempotency():readIssuanceRecovery(window.sessionStorage,`tokansh-issuance-v1:${session!.user_id}:${selected.id}`)?.key||idempotency();
   if(typeof window!=='undefined')writeIssuanceRecovery(window.sessionStorage,`tokansh-issuance-v1:${session!.user_id}:${selected.id}`,{key});
   const result=parseIssuance(await request<unknown>(route.issuances,{method:'POST',body:{property_id:selected.id,quantity:selected.approved_supply,issue_price_minor:issuePrice,currency:'INR'},idempotencyKey:key,correlationId:key}));
   if(typeof window!=='undefined')writeIssuanceRecovery(window.sessionStorage,`tokansh-issuance-v1:${session!.user_id}:${selected.id}`,{key,operationId:result.operation_id,result});
   return result;
  },onSuccess:result=>{setOperation(result);setError('');void queryClient.invalidateQueries({queryKey:['issuer-properties',session?.user_id]});void queryClient.invalidateQueries({queryKey:['issuer-balance',session?.user_id,selected?.id]});},onError:value=>setError(errorFeedback(value))});
 const alreadyIssued=Boolean(operation&&['COMMITTED_VALID','COMMITTED_INVALID','SUBMITTED','SUBMISSION_PENDING','UNKNOWN','RECONCILIATION_REQUIRED'].includes(operation.state))||Boolean(balance.data&&selected&&balance.data>0);
 return <><SectionHeading title="ANSH Issuance" description="Issue the complete approved supply to the authenticated property issuer after committed registration."/>
  <div className="grid gap-4 md:grid-cols-3"><Metric label="Authenticated issuer" value={session?.display_name||'Unavailable'} description="Derived from the bearer session"/><Metric label="Selected property" value={selected?.name||'None'} description={selected?propertyTokenId(selected.id):'Create a property first'}/><Metric label="Issued supply" value={ledgerState.data?integer(ledgerState.data.issued_supply):'—'} description="Authoritative DRUNIX state"/></div>
  <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_1fr]">
   <Card title="Initiate issuance" description="The request always uses the entire approved supply and the registered property issuer.">
    <form className="space-y-4" onSubmit={e=>{e.preventDefault();if(!alreadyIssued)issue.mutate();}}>
     <SelectField label="Registered property" id="connected-issue-property" value={selected?.id||''} onChange={e=>setSelectedId(e.target.value)}><option value="">Select property</option>{own.map(value=><option key={value.id} value={value.id}>{value.name} · {propertyTokenId(value.id)}</option>)}</SelectField>
     <Field id="connected-issue-quantity" label="Full approved supply" value={selected?String(selected.approved_supply):'—'} readOnly/>
     <Field id="connected-issue-price" label="Initial issue price / ANSH (INR)" value={selected?.unit_price||'—'} readOnly/>
     <dl><DataRow label="Registration" value={<Status value={selected?.ledger_registration_status==='REGISTERED'?'COMMITTED':'UNAVAILABLE'}/>}/><DataRow label="Issuer binding" value={selected?.issuer_id===session?.user_id?'Authenticated investor':'Rejected'}/><DataRow label="Token identity" value={selected?propertyTokenId(selected.id):'—'}/></dl>
     {error&&<p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">{error}</p>}
     <Button type="submit" disabled={!selected||selected.ledger_registration_status!=='REGISTERED'||selected.approved_supply<=0||alreadyIssued||issue.isPending}>{issue.isPending?'Submitting…':alreadyIssued?'Issuance already submitted':'Issue full approved supply'} <ArrowRight size={15}/></Button>
    </form>
   </Card>
   <Card title="Authoritative issuance status" description="Success is shown only after the backend verifies ledger commitment.">
    <dl><DataRow label="Operation" value={operation?.operation_id||'Not initiated'}/><DataRow label="State" value={<Status value={operation?.state||'UNAVAILABLE'}/>}/><DataRow label="Transaction" value={operation?.transaction_id||'—'}/><DataRow label="Issued supply" value={ledgerState.data?integer(ledgerState.data.issued_supply):'—'}/><DataRow label="Ownership confirmed" value={operation?.ownership_confirmed?'Yes':'Not confirmed'}/><DataRow label="Current issuer holdings" value={balance.data===undefined?'—':integer(balance.data)+' ANSH'}/></dl>
    <p className="mt-5 text-xs leading-6 text-slate-500">Pending or uncertain operations remain recoverable through the operation status and reconciliation endpoints. No local preview state is treated as ledger ownership.</p>
   </Card>
  </div></>;
}
function PreviewIssuance(){
 const {property,phase,submit,submitting}=usePreview();
 const [quantity,setQuantity]=useState(100000),[open,setOpen]=useState(false);
 const allowed=phaseIndex(phase)>=1&&property.approvedSupply>=quantity&&quantity>0;
 const payload:NewIssuance={property_id:sample.id,quantity,issue_price_minor:String(Math.round(Number(sample.unitPrice)*100)),currency:'INR'};
 return <><SectionHeading title="ANSH Issuance" description="Issue only against an approved property whose DRUNIX registration has actually committed."/>
 <div className="grid gap-4 md:grid-cols-3"><Metric label="Approved supply" value={integer(sample.approvedSupply)} description="TechPark One"/><Metric label="Issued units · preview" value={integer(property.issued)} description="No verified DRUNIX issuance"/><Metric label="Remaining in scenario" value={integer(sample.approvedSupply-property.issued)} description="Illustrative only"/></div>
 <div className="mt-5 grid gap-5 xl:grid-cols-[1.1fr_1fr]">
 <Card title="Initiate issuance" description="Exact issue price, quantity and currency are reviewed before submission">
 <form className="space-y-4" onSubmit={e=>{e.preventDefault();if(allowed)setOpen(true);}}>
 <Field id="issue-prop" label="Property" value={sample.name} readOnly/>
 <Field id="issue-quantity" label="Requested issuance quantity" type="number" min={1} max={sample.approvedSupply} step={1} value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/>
 <Field id="issue-price" label="Issue price / ANSH (INR)" value={sample.unitPrice} readOnly/>
 <dl><DataRow label="Issue currency" value="INR"/><DataRow label="Total issuance value" value={inr(quantity*Number(sample.unitPrice))}/><DataRow label="Approval stage" value={<Status value={property.approval}/>}/><DataRow label="DRUNIX asset registration" value={<Status value="UNAVAILABLE"/>}/></dl>
 <Button type="submit" disabled={!allowed||submitting}>Review issuance request <ArrowRight size={15}/></Button>
 {!allowed&&<p className="text-xs text-amber-800">Select the approved scenario before previewing issuance. Real issuance additionally requires a committed DRUNIX property registration.</p>}
 </form></Card>
 <Card title="Issuance status" description="Keep business status separate from blockchain finality">
 <dl><DataRow label="Application workflow" value={phaseIndex(phase)>=2?'Illustrative issuance phase':'Not initiated'}/><DataRow label="Ledger submission" value={<Status value="UNAVAILABLE"/>}/><DataRow label="Transaction identifier" value="Not available"/><DataRow label="Ledger commitment" value="Unverified"/><DataRow label="Confirmed issued supply" value="Backend query required"/></dl>
 <p className="mt-5 text-xs leading-6 text-slate-500">No success state can be displayed until the Python backend confirms an actual DRUNIX transaction and a verified ledger query.</p></Card></div>
 <ReviewDialog open={open} onOpenChange={setOpen} title="Review ANSH issuance" description="This request requires authorization, committed property registration and actual DRUNIX transaction finality." onConfirm={async()=>{await submit(route.issuances,payload);setOpen(false);}} busy={submitting} confirmLabel="Submit issuance request"><dl><DataRow label="Property" value={sample.name}/><DataRow label="Quantity" value={integer(quantity)+' ANSH'}/><DataRow label="Issue price" value={inr(sample.unitPrice)}/><DataRow label="Total value" value={inr(quantity*Number(sample.unitPrice))}/></dl></ReviewDialog>
 </>;
}
export function Marketplace(){const {mode}=useApp();return mode==='real'?<ConnectedMarketplace/>:<PreviewMarketplace/>;}
function PreviewMarketplace(){
 const {phase,property,holding,submit,submitting}=usePreview();
 const [quantity,setQuantity]=useState(500),[open,setOpen]=useState(false),[showDetails,setShowDetails]=useState(false);
 const listingReady=phaseIndex(phase)>=2;
 const valid=Number.isSafeInteger(quantity)&&quantity>0&&quantity<=sample.approvedSupply;
 const order:NewOrder={listing_id:'LISTING-TECHPARK-DEMO',quantity,currency:'INR'};
 return <><SectionHeading title="Marketplace" description="Discover ANSH economic interests and review the payment-versus-ledger settlement boundary."/>
 <div className="grid gap-5 xl:grid-cols-[1fr_1.2fr]">
 <Card className="overflow-hidden !p-0"><img className="h-56 w-full object-cover" src={propertyImage} alt="Illustrative commercial office property"/><div className="p-5">
 <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-xs font-semibold text-[#1769AA]">COMMERCIAL OFFICE · BENGALURU</p><h2 className="mt-1 text-xl font-bold text-[#102B4E]">TechPark One</h2><p className="mt-1 text-xs text-slate-500">Synthetic Grade-A real estate investment opportunity</p></div><Status value="PREVIEW_ONLY"/></div>
 <dl className="mt-5"><DataRow label="Illustrative property valuation" value={inr(sample.valuation,true)}/><DataRow label="ANSH price" value={inr(sample.unitPrice)}/><DataRow label="Listing owner" value="Meera · Issuer preview"/><DataRow label="Listed quantity" value={listingReady?'100,000 ANSH (illustrative)':'Not yet issued'}/><DataRow label="Listing state" value={listingReady?'Preview stage: available':'Unavailable'}/></dl>
 <Button variant="secondary" className="mt-4" onClick={()=>setShowDetails(v=>!v)}>{showDetails?'Hide':'View'} property details</Button>
 {showDetails&&<div className="mt-4 rounded-lg border border-slate-200 p-4 text-xs leading-6 text-slate-600"><p><strong>Legal nature:</strong> ANSH represents an economic interest within the defined product model, not automatic registered ownership of the property.</p><p><strong>Valuation:</strong> indicative only; no verified appraisal.</p><p><strong>Ownership:</strong> authoritative records must be obtained from DRUNIX through Python APIs.</p><p><strong>Rental income:</strong> eligibility depends on verified record-date ownership.</p></div>}
 </div></Card>
 <div className="space-y-5"><Card title="Purchase ANSH" description="Investor purchase · payment and transfer are separate">
  <form className="space-y-4" onSubmit={e=>{e.preventDefault();if(valid)setOpen(true);}}>
   <Field id="order-asset" label="Asset" value={sample.name} readOnly/>
   <Field id="order-quantity" label="Purchase quantity" type="number" min={1} max={sample.approvedSupply} step={1} value={quantity} onChange={e=>setQuantity(Number(e.target.value))}/>
   <dl><DataRow label="Price / ANSH" value={inr(sample.unitPrice)}/><DataRow label="Purchase amount" value={inr(quantity*Number(sample.unitPrice))}/><DataRow label="Investor preview holdings" value={integer(holding.owned)+' ANSH'}/><DataRow label="DRUNIX connectivity" value={<Status value="UNAVAILABLE"/>}/></dl>
   {!listingReady&&<p className="text-xs text-amber-700">Select an issued preview stage to inspect the purchase form. A real listing requires confirmed DRUNIX issuance.</p>}
   <Button type="submit" disabled={!valid||!listingReady||submitting}>Review purchase <ArrowRight size={15}/></Button>
  </form></Card>
  <Card title="Purchase & settlement timeline" description="Each stage requires independent evidence"><TransitionTimeline phase={phase}/></Card></div>
 </div>
 <div className="mt-5"><PreviewWarning/></div>
 <ReviewDialog open={open} onOpenChange={setOpen} title="Review purchase order" description="Submitting an order is not equivalent to payment or DRUNIX commitment. No ownership updates are performed by the frontend." onConfirm={async()=>{await submit(route.orders,order);setOpen(false);}} busy={submitting} confirmLabel="Submit order request"><dl><DataRow label="Property" value={sample.name}/><DataRow label="Quantity" value={integer(quantity)+' ANSH'}/><DataRow label="Payment amount" value={inr(quantity*Number(sample.unitPrice))}/><DataRow label="Payment type" value="Simulated by backend only"/><DataRow label="Ledger finality" value="Await actual DRUNIX commit"/></dl></ReviewDialog>
 </>;
}
