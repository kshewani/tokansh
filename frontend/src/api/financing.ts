import {isRecord,RequestError} from './client.ts';
export const financeStates=['APPLIED','ASSESSED','APPROVED','REJECTED','DISBURSED','REPAID','RELEASED'] as const;
export type FinanceState=typeof financeStates[number];
export type FinanceCommand={property_id:string;asset_class:'ANSH';quantity:number;lender_id?:string;offer_id?:string;unit_value_minor:string;ltv_percent:number;annual_rate_bps:number;term_months:number};
export type Loan=FinanceCommand&{id:string;borrower_id:string;type:'SIMULATED_FINANCING';state:FinanceState;simulated:true;on_chain_lock:false;reservation_active:boolean;collateral_value_minor:string;principal_minor:string;interest_minor:string;repayment_minor:string;outstanding_principal_minor:string;amount_due_minor:string;created_at:string;updated_at:string;assessment:null|{simulated:true;eligible:boolean;observed_owned:number;ownership_source:'DRUNIX_EVALUATE';observed_at:string;risk_band:'MODERATE'|'ELEVATED';reason:string};timeline:{state:FinanceState;timestamp:string;actor_role:string;simulated:true}[]};
export type Eligibility={property_id:string;holder_id:string;owned:number;reserved_simulated:number;eligible_simulated:number;reservation_shortfall:boolean;on_chain_lock:false;ownership_source:'DRUNIX_EVALUATE';observed_at:string};
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const money=(v:unknown):v is string=>typeof v==='string'&&/^(0|[1-9][0-9]*)$/.test(v);
const units=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
function bad():never{throw new RequestError(200,'MALFORMED_RESPONSE','The financing simulation response is inconsistent. Refresh its saved state.');}
export function financeQuote(quantity:number,unit:string,ltv:number,rate:number,months:number){
 if(!Number.isSafeInteger(quantity)||quantity<1||!money(unit)||BigInt(unit)<1n||BigInt(unit)>999999999999n||!Number.isInteger(ltv)||ltv<20||ltv>75||!Number.isInteger(rate)||rate<1||rate>3000||!Number.isInteger(months)||months<1||months>36)throw new Error('Enter valid illustrative terms.');
 const collateral=BigInt(quantity)*BigInt(unit),principal=collateral*BigInt(ltv)/100n;
 if(principal<1n)throw new Error('The illustrative advance is too small.');
 const interest=(principal*BigInt(rate)*BigInt(months)+60000n)/120000n;
 return {collateral_value_minor:String(collateral),principal_minor:String(principal),interest_minor:String(interest),repayment_minor:String(principal+interest)};
}
export function rupeesToMinor(value:string){
 if(!/^[0-9]{1,10}(\.[0-9]{1,2})?$/.test(value))throw new Error('Use a positive INR amount with at most two decimals.');
 const [whole,fraction='']=value.split('.');const result=BigInt(whole)*100n+BigInt(fraction.padEnd(2,'0'));
 if(result<1n||result>999999999999n)throw new Error('Illustrative unit value is out of range.');
 return String(result);
}
export function moneyINR(value:string){
 if(!money(value))return '—';const v=BigInt(value);
 return '₹'+(v/100n).toLocaleString('en-IN')+'.'+(v%100n).toString().padStart(2,'0');
}
export function parseLoan(value:unknown):Loan{
 if(!isRecord(value)||value.type!=='SIMULATED_FINANCING'||value.simulated!==true||value.on_chain_lock!==false||value.asset_class!=='ANSH'||
  ![value.id,value.borrower_id,value.property_id].every(v=>typeof v==='string'&&uuid.test(v))||!financeStates.includes(value.state as FinanceState)||typeof value.reservation_active!=='boolean'||
  !units(value.quantity)||value.quantity<1||typeof value.unit_value_minor!=='string'||
  !['collateral_value_minor','principal_minor','interest_minor','repayment_minor','outstanding_principal_minor','amount_due_minor'].every(k=>money(value[k]))||
  !Array.isArray(value.timeline)||!value.timeline.length||!value.timeline.every(e=>isRecord(e)&&financeStates.includes(e.state as FinanceState)&&e.simulated===true&&typeof e.actor_role==='string'&&typeof e.timestamp==='string'&&Number.isFinite(Date.parse(e.timestamp)))||
  value.timeline[value.timeline.length-1].state!==value.state)return bad();
 if(('lender_id' in value&&(typeof value.lender_id!=='string'||!value.lender_id))||('offer_id' in value&&(typeof value.offer_id!=='string'||!value.offer_id)))return bad();
 let q;try{q=financeQuote(value.quantity,value.unit_value_minor,value.ltv_percent as number,value.annual_rate_bps as number,value.term_months as number);}catch{return bad();}
 if(Object.entries(q).some(([k,v])=>value[k]!==v)||value.reservation_active!==['APPROVED','DISBURSED','REPAID'].includes(String(value.state))||
  value.outstanding_principal_minor!==(value.state==='DISBURSED'?value.principal_minor:'0')||value.amount_due_minor!==(value.state==='DISBURSED'?value.repayment_minor:'0'))return bad();
 if(value.assessment!==null&&(!isRecord(value.assessment)||value.assessment.simulated!==true||typeof value.assessment.eligible!=='boolean'||!units(value.assessment.observed_owned)||value.assessment.ownership_source!=='DRUNIX_EVALUATE'||!['MODERATE','ELEVATED'].includes(String(value.assessment.risk_band))||typeof value.assessment.reason!=='string'))return bad();
 return value as Loan;
}
export function parseEligibility(value:unknown,property:string,holder:string):Eligibility{
 if(!isRecord(value)||value.property_id!==property||value.holder_id!==holder||value.ownership_source!=='DRUNIX_EVALUATE'||value.on_chain_lock!==false||
  !units(value.owned)||!units(value.reserved_simulated)||!units(value.eligible_simulated)||value.eligible_simulated!==Math.max(0,value.owned-value.reserved_simulated)||value.reservation_shortfall!==(value.reserved_simulated>value.owned)||(typeof value.observed_at!=='string'||!Number.isFinite(Date.parse(value.observed_at))))return bad();
 return value as Eligibility;
}
