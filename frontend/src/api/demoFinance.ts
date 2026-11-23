import {isRecord,RequestError} from './client.ts';
export type Offer={id:string;annual_rate_bps:number;max_ltv_percent:number;tenures_months:number[]};
export type Lender={id:string;name:string;simulated:true;offers:Offer[]};
export type Cash={investor_id:string;balance_minor:string;currency:'INR';simulated:true};
export type CashEntry={id:string;kind:'DEMO_FUNDS'|'WITHDRAWAL'|'DISBURSEMENT'|'REPAYMENT';amount_minor:string;balance_after_minor:string;loan_id:string|null;created_at:string;currency:'INR';simulated:true;status:'SIMULATED_COMPLETED'};
const amount=(v:unknown)=>typeof v==='string'&&/^(0|[1-9][0-9]*)$/.test(v)&&BigInt(v)<=9007199254740991n;
function invalid():never{throw new RequestError(200,'MALFORMED_RESPONSE','Demo finance response could not be verified. Refresh saved activity before repeating an action.');}
export function parseLenders(value:unknown):Lender[]{
 if(!Array.isArray(value)||!value.length)return invalid();
 const ids=new Set();
 for(const l of value){if(!isRecord(l)||typeof l.id!=='string'||!l.id||ids.has(l.id)||typeof l.name!=='string'||l.simulated!==true||!Array.isArray(l.offers)||!l.offers.length)return invalid();ids.add(l.id);
 const offers=new Set();for(const o of l.offers){if(!isRecord(o)||typeof o.id!=='string'||offers.has(o.id)||!Number.isInteger(o.annual_rate_bps)||Number(o.annual_rate_bps)<1||Number(o.annual_rate_bps)>3000||!Number.isInteger(o.max_ltv_percent)||Number(o.max_ltv_percent)<20||Number(o.max_ltv_percent)>75||!Array.isArray(o.tenures_months)||!o.tenures_months.length||!o.tenures_months.every(n=>Number.isInteger(n)&&n>0&&n<=36))return invalid();offers.add(o.id);}}
 return value as Lender[];
}
export function parseCash(value:unknown,holder:string):Cash{if(!isRecord(value)||value.investor_id!==holder||!amount(value.balance_minor)||value.currency!=='INR'||value.simulated!==true)return invalid();return value as Cash;}
export function parseEntry(value:unknown):CashEntry{if(!isRecord(value)||typeof value.id!=='string'||!['DEMO_FUNDS','WITHDRAWAL','DISBURSEMENT','REPAYMENT'].includes(String(value.kind))||!amount(value.amount_minor)||value.amount_minor==='0'||!amount(value.balance_after_minor)||value.currency!=='INR'||value.simulated!==true||value.status!=='SIMULATED_COMPLETED'||typeof value.created_at!=='string'||!Number.isFinite(Date.parse(value.created_at))||!(value.loan_id===null||typeof value.loan_id==='string'))return invalid();return value as CashEntry;}

/** Stable cash key survives navigation. Only explicit confirmation sends a request. */
export function createCashFlow(store:()=>Pick<Storage,'getItem'|'setItem'|'removeItem'>,newKey:()=>string,userId='anonymous'){
 let pending=false;
 const storageKey='tokansh-demo-cash-attempt-v1:'+userId;
 function snapshot(){const raw=store().getItem(storageKey);if(!raw)return null;let value:unknown;try{value=JSON.parse(raw);}catch{return invalid();}
 if(!isRecord(value)||!['fund','withdraw'].includes(String(value.action))||!amount(value.amount)||typeof value.key!=='string'||!value.key)return invalid();
 return value as {action:'fund'|'withdraw';amount:string;key:string};}
 return {snapshot,async run(action:'fund'|'withdraw',value:string,send:(key:string)=>Promise<unknown>){
 if(pending)throw new RequestError(409,'OPERATION_PENDING','A cash request is already in progress.');
 pending=true;
 try{let previous=snapshot();if(previous&&(previous.action!==action||previous.amount!==value))throw new RequestError(409,'RECONCILIATION_REQUIRED','Use the saved cash action and amount to resolve the original request.');
 if(!previous){previous={action,amount:value,key:newKey()};store().setItem(storageKey,JSON.stringify(previous));}
 try{const result=parseEntry(await send(previous.key));if(result.amount_minor!==value||result.kind!==(action==='fund'?'DEMO_FUNDS':'WITHDRAWAL'))return invalid();store().removeItem(storageKey);return result;}
 catch(error){if(error instanceof RequestError&&!error.requiresReconciliation&&error.status>=400&&error.status<500)store().removeItem(storageKey);throw error;}
 }finally{pending=false;}
 }};
}
