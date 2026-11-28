import type {FinanceState,Loan} from './financing.ts';

export type ActivityFilter='ALL'|'PENDING'|'APPROVED'|'DISBURSED'|'CLOSED'|'REJECTED';
export type ActivityRange='7'|'30'|'90'|'ALL';
export type ActivityProperty={name?:string;location?:string;ansh_symbol?:string};

export function statusCategory(state:FinanceState):Exclude<ActivityFilter,'ALL'>{
 if(state==='APPLIED'||state==='ASSESSED')return 'PENDING';
 if(state==='APPROVED')return 'APPROVED';
 if(state==='DISBURSED')return 'DISBURSED';
 if(state==='REPAID'||state==='RELEASED')return 'CLOSED';
 return 'REJECTED';
}

export function rangeCutoff(range:ActivityRange,now=Date.now()):number|null{
 if(range==='ALL')return null;
 return now-Number(range)*24*60*60*1000;
}

export function eventInRange(timestamp:string,cutoff:number|null):boolean{
 const value=Date.parse(timestamp);
 return Number.isFinite(value)&&(cutoff===null||value>=cutoff);
}

export function scopedEvents(loan:Loan,cutoff:number|null){
 return loan.timeline.filter(event=>eventInRange(event.timestamp,cutoff));
}

export function matchesFilter(loan:Loan,filter:ActivityFilter,cutoff:number|null):boolean{
 if(!applicationInScope(loan,cutoff))return false;
 return filter==='ALL'||statusCategory(loan.state)===filter;
}

export function latestScopedEvent(loan:Loan,cutoff:number|null){
 return scopedEvents(loan,cutoff).slice().sort((a,b)=>Date.parse(b.timestamp)-Date.parse(a.timestamp))[0]||null;
}

export function applicationInScope(loan:Loan,cutoff:number|null):boolean{
 return loan.timeline.some(event=>event.state==='APPLIED'&&eventInRange(event.timestamp,cutoff))||
  (!loan.timeline.some(event=>event.state==='APPLIED')&&eventInRange(loan.created_at,cutoff));
}

export function filterActivity(loans:Loan[],query:string,filter:ActivityFilter,cutoff:number|null,properties:Record<string,ActivityProperty>){
 const needle=query.trim().toLowerCase();
 return loans.filter(loan=>{
  if(!matchesFilter(loan,filter,cutoff))return false;
  if(!needle)return true;
  const property=properties[loan.property_id];
  return [loan.id,loan.borrower_id,loan.property_id,property?.name,property?.location,property?.ansh_symbol]
   .filter((value):value is string=>typeof value==='string').some(value=>value.toLowerCase().includes(needle));
 }).sort((a,b)=>(Date.parse(latestScopedEvent(b,cutoff)?.timestamp||b.updated_at)-Date.parse(latestScopedEvent(a,cutoff)?.timestamp||a.updated_at)));
}

export function eventCount(loans:Loan[],filter:ActivityFilter,cutoff:number|null):number{
 return loans.filter(loan=>matchesFilter(loan,filter,cutoff)).length;
}

export function lenderSummary(loans:Loan[],cutoff:number|null){
 const applications=loans.filter(loan=>applicationInScope(loan,cutoff));
 const approved=loans.filter(loan=>scopedEvents(loan,cutoff).some(event=>event.state==='APPROVED')).length;
 const disbursed=loans.filter(loan=>scopedEvents(loan,cutoff).some(event=>event.state==='DISBURSED'));
 const repaid=loans.filter(loan=>scopedEvents(loan,cutoff).some(event=>event.state==='REPAID'));
 const disbursedMinor=disbursed.reduce((total,loan)=>total+BigInt(loan.principal_minor),0n).toString();
 const repaidMinor=repaid.reduce((total,loan)=>total+BigInt(loan.repayment_minor),0n).toString();
 return {applications:applications.length,approved,disbursed:disbursed.length,disbursedMinor,repaid:repaid.length,repaidMinor};
}
