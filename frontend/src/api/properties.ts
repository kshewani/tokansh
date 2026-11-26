import {isRecord,RequestError} from './client.ts';
import type {ApiRequest} from './transfers.ts';
import type {IssuanceResult,PortfolioItem,PortfolioRecord,PropertyIssuanceState,PropertyRecord} from './contracts.ts';

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const DEFAULT_INITIAL_PRICE_MINOR=100000;
export const DEFAULT_INITIAL_PRICE_RUPEES='1000';
export const propertyTokenId=(propertyId:string)=>`ANSH-${propertyId.trim().toLowerCase()}`;

function malformed():never{throw new RequestError(200,'MALFORMED_RESPONSE','The API returned an invalid property or issuance record.');}
function integer(value:unknown):value is number{return typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;}

export function parseProperty(value:unknown):PropertyRecord{
 if(!isRecord(value)||typeof value.id!=='string'||!uuid.test(value.id)||typeof value.name!=='string'||
  typeof value.location!=='string'||typeof value.category!=='string'||typeof value.valuation!=='string'||
  !integer(value.proposed_supply)||!integer(value.approved_supply)||typeof value.unit_price!=='string'||
  value.currency!=='INR'||typeof value.status!=='string'||typeof value.issuer_id!=='string'||
  typeof value.verification_status!=='string'||!['NOT_REGISTERED','REGISTERED'].includes(String(value.ledger_registration_status))||
  (value.ledger_transaction_id!==null&&typeof value.ledger_transaction_id!=='string'))return malformed();
 return value as PropertyRecord;
}

export function parsePropertyPage(value:unknown):PropertyRecord[]{
 if(!isRecord(value)||!Array.isArray(value.items))return malformed();
 return value.items.map(parseProperty);
}

function issuanceState(value:unknown):value is IssuanceResult['state']{
 return ['PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','COMMITTED_VALID','COMMITTED_INVALID','FAILED','UNKNOWN','RECONCILIATION_REQUIRED'].includes(String(value));
}
export function parseIssuance(value:unknown,operationId?:string):IssuanceResult{
 if(!isRecord(value)||typeof value.operation_id!=='string'||!uuid.test(value.operation_id)||(operationId&&value.operation_id!==operationId)||
  !issuanceState(value.state)||typeof value.transaction_id!=='string'&&value.transaction_id!==null||!isRecord(value.request)||
  typeof value.request.property_id!=='string'||!uuid.test(value.request.property_id)||!integer(value.request.quantity)||
  typeof value.request.issue_price_minor!=='string'||value.request.currency!=='INR'||
  (value.commit!==null&&!isRecord(value.commit))||(value.error_code!==null&&typeof value.error_code!=='string')||
  typeof value.ownership_confirmed!=='boolean')return malformed();
 return value as IssuanceResult;
}

export function deriveSupply(valuationRupees:string,priceMinor=DEFAULT_INITIAL_PRICE_MINOR):number|null{
 const match=valuationRupees.trim().match(/^(0|[1-9][0-9]*)(?:\.([0-9]{1,2}))?$/);
 if(!match)return null;
 const minor=BigInt(match[1])*100n+BigInt((match[2]||'').padEnd(2,'0')||'0');
 const price=BigInt(priceMinor);
 if(minor<=0n||price<=0n||minor%price!==0n)return null;
 const supply=minor/price;
 return supply<=9007199254740991n?Number(supply):null;
}

export function rupeesToMinor(value:string):string|null{
 const match=value.trim().match(/^(0|[1-9][0-9]*)(?:\.([0-9]{1,2}))?$/);
 if(!match)return null;
 const minor=BigInt(match[1])*100n+BigInt((match[2]||'').padEnd(2,'0')||'0');
 return minor>0n?minor.toString():null;
}

export function parsePropertyIssuanceState(value:unknown,propertyId:string):PropertyIssuanceState{
 if(!isRecord(value)||value.property_id!==propertyId||!integer(value.approved_supply)||!integer(value.issued_supply)||
  !integer(value.remaining_supply)||typeof value.state!=='string'||value.source!=='DRUNIX')return malformed();
 return value as PropertyIssuanceState;
}

export function parseBalanceQuantity(value:unknown,propertyId:string,holderId:string):number{
 if(!isRecord(value)||value.schema_version!==1||value.property_id!==propertyId||value.holder_id!==holderId||!integer(value.quantity))return malformed();
 return value.quantity;
}

export function parsePortfolio(value:unknown,investorId:string):PortfolioRecord{
 const statuses=['AVAILABLE','UNAVAILABLE'],issuance=['ISSUED','REGISTERED','UNAVAILABLE'];
 if(!isRecord(value)||value.investor_id!==investorId||value.currency!=='INR'||value.source!=='DRUNIX_EVALUATE'||!Array.isArray(value.items)||!isRecord(value.aggregate))return malformed();
 const aggregate=value.aggregate;
 const observedPropertyCount=aggregate.observed_property_count;
 if(!['COMPLETE','PARTIAL','UNAVAILABLE'].includes(String(aggregate.status))||typeof observedPropertyCount!=='number'||!Number.isSafeInteger(observedPropertyCount)||observedPropertyCount<0||
  !(aggregate.total_indicative_value_minor===null||/^(0|[1-9][0-9]*)$/.test(String(aggregate.total_indicative_value_minor)))||
  !(aggregate.valuation_basis===null||aggregate.valuation_basis==='INITIAL_ISSUE_PRICE'))return malformed();
 const items=value.items.map(item=>{
  if(!isRecord(item)||typeof item.property_id!=='string'||!uuid.test(item.property_id)||item.ansh_id!==propertyTokenId(item.property_id)||
   typeof item.name!=='string'||typeof item.category!=='string'||typeof item.location!=='string'||typeof item.issuer_id!=='string'||!uuid.test(item.issuer_id)||
   !['REGISTERED','NOT_REGISTERED'].includes(String(item.registration_status))||!issuance.includes(String(item.issuance_status))||
   !/^[0-9]+$/.test(String(item.approved_valuation_minor))||!/^[1-9][0-9]*$/.test(String(item.initial_issue_price_minor))||item.currency!=='INR'||
   !integer(item.approved_supply)||!(item.issued_supply===null||integer(item.issued_supply))||!(item.owned_units===null||integer(item.owned_units))||
   !integer(item.pledged_units)||!integer(item.offering_committed_units)||!(item.transferable_units===null||integer(item.transferable_units))||
   !statuses.includes(String(item.observation_status))||item.source!=='DRUNIX_EVALUATE'||!(item.observed_at===null||typeof item.observed_at==='string')||
   !(item.error_code===null||typeof item.error_code==='string'))return malformed();
  if(item.observation_status==='AVAILABLE'&&(item.issued_supply===null||item.owned_units===null||item.observed_at===null))return malformed();
  if(item.observation_status==='UNAVAILABLE'&&(item.owned_units!==null||item.issued_supply!==null))return malformed();
  return item as PortfolioItem;
 });
 const unavailableItems=items.filter(item=>item.observation_status==='UNAVAILABLE');
 const aggregateStatus=String(aggregate.status);
 if(aggregateStatus==='COMPLETE'&&unavailableItems.length>0)return malformed();
 if(aggregateStatus==='PARTIAL'&&(
  unavailableItems.length===0||aggregate.total_indicative_value_minor!==null||aggregate.valuation_basis!==null
 ))return malformed();
 if(aggregateStatus==='UNAVAILABLE'&&(
  unavailableItems.length!==items.length||observedPropertyCount!==0||aggregate.total_indicative_value_minor!==null||aggregate.valuation_basis!==null
 ))return malformed();
 return {...value,items} as PortfolioRecord;
}

export type IssuanceRecovery={key:string;operationId?:string;result?:IssuanceResult};
export function issuanceStorageKey(userId:string,propertyId:string){return `tokansh-issuance-v1:${userId}:${propertyId}`;}
export function readIssuanceRecovery(store:Pick<Storage,'getItem'>|null|undefined,key:string):IssuanceRecovery|null{
 try{const raw=store?.getItem(key);if(!raw)return null;const value:unknown=JSON.parse(raw);if(!isRecord(value)||typeof value.key!=='string'||(value.operationId!==undefined&&typeof value.operationId!=='string'))return null;return value as IssuanceRecovery;}catch{return null;}
}
export function writeIssuanceRecovery(store:Pick<Storage,'setItem'>|null|undefined,key:string,value:IssuanceRecovery){try{store?.setItem(key,JSON.stringify(value));}catch{/* Recovery remains visible in React state. */}}
export function clearIssuanceRecovery(store:Pick<Storage,'removeItem'>|null|undefined,key:string){try{store?.removeItem(key);}catch{/* Keep the operation unresolved if storage cannot be cleared. */}}

export type PropertyApi={request:ApiRequest;propertyId:string;userId:string};
