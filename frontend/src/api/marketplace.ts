import {isRecord,RequestError} from './client.ts';
import type {ApiRequest} from './transfers.ts';

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const integer=(value:unknown):value is number=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0;
const money=(value:unknown):value is string=>typeof value==='string'&&/^[1-9][0-9]*$/.test(value);
const nonNegativeMoney=(value:unknown):value is string=>value==='0'||money(value);
function malformed():never{throw new RequestError(200,'MALFORMED_RESPONSE','The marketplace response was invalid.');}

export type OfferingStatus='ACTIVE'|'SOLD_OUT'|'CLOSED';
export type Offering={id:string;property_id:string;issuer_id:string;offered_quantity:number;sold_quantity:number;reserved_quantity:number;available_quantity:number;price_minor:string;currency:'INR';status:OfferingStatus;created_at:string;updated_at:string};
export type PurchaseState='RESERVED'|'PREPARING'|'PREPARED'|'SUBMISSION_PENDING'|'SUBMITTED'|'UNKNOWN'|'COMMITTED_PENDING_SETTLEMENT'|'SETTLED'|'FAILED'|'COMMITTED_INVALID'|'RECONCILIATION_REQUIRED';
export type Purchase={operation_id:string;offering_id:string;property_id:string;buyer_id:string;seller_id:string;quantity:number;price_minor:string;total_amount_minor:string;currency:'INR';state:PurchaseState;transfer_operation_id:string|null;transaction_id:string|null;error_code:string|null;created_at:string;updated_at:string};
export type WalletBalance={investor_id:string;balance_minor:string;reserved_minor:string;available_minor:string;currency:'INR';simulated:true};
export function parseOffering(value:unknown):Offering{
 if(!isRecord(value)||typeof value.id!=='string'||!uuid.test(value.id)||typeof value.property_id!=='string'||!uuid.test(value.property_id)||typeof value.issuer_id!=='string'||!uuid.test(value.issuer_id)||
  !integer(value.offered_quantity)||value.offered_quantity<1||!integer(value.sold_quantity)||!integer(value.reserved_quantity)||!integer(value.available_quantity)||
  value.available_quantity!==value.offered_quantity-value.sold_quantity-value.reserved_quantity||!money(value.price_minor)||value.currency!=='INR'||
  !['ACTIVE','SOLD_OUT','CLOSED'].includes(String(value.status))||typeof value.created_at!=='string'||typeof value.updated_at!=='string')return malformed();
 return value as Offering;
}
export function parseOfferings(value:unknown):Offering[]{if(!Array.isArray(value))return malformed();return value.map(parseOffering);}
export function parsePurchase(value:unknown):Purchase{
 if(!isRecord(value)||typeof value.operation_id!=='string'||!uuid.test(value.operation_id)||typeof value.offering_id!=='string'||!uuid.test(value.offering_id)||typeof value.property_id!=='string'||!uuid.test(value.property_id)||
  typeof value.buyer_id!=='string'||!uuid.test(value.buyer_id)||typeof value.seller_id!=='string'||!uuid.test(value.seller_id)||!integer(value.quantity)||value.quantity<1||
  !money(value.price_minor)||!money(value.total_amount_minor)||value.currency!=='INR'||!['RESERVED','PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','UNKNOWN','COMMITTED_PENDING_SETTLEMENT','SETTLED','FAILED','COMMITTED_INVALID','RECONCILIATION_REQUIRED'].includes(String(value.state))||
  value.buyer_id===value.seller_id||(value.transfer_operation_id!==null&&typeof value.transfer_operation_id!=='string')||(value.transaction_id!==null&&typeof value.transaction_id!=='string')||(value.error_code!==null&&typeof value.error_code!=='string'))return malformed();
 try{if(BigInt(value.total_amount_minor as string)!==BigInt(value.quantity as number)*BigInt(value.price_minor as string))return malformed();}catch{return malformed();}
 return value as Purchase;
}
export function parseWalletBalance(value:unknown,investorId:string):WalletBalance{
 if(!isRecord(value)||value.investor_id!==investorId||!nonNegativeMoney(value.balance_minor)||!nonNegativeMoney(value.reserved_minor)||!nonNegativeMoney(value.available_minor)||value.currency!=='INR'||value.simulated!==true)return malformed();
 try{if(BigInt(value.reserved_minor as string)>BigInt(value.balance_minor as string)||BigInt(value.available_minor as string)!==BigInt(value.balance_minor as string)-BigInt(value.reserved_minor as string))return malformed();}catch{return malformed();}
 return value as WalletBalance;
}
export const purchaseStorageKey=(userId:string,offeringId:string)=>`tokansh-purchase-v1:${userId}:${offeringId}`;
export type PurchaseRecovery={key:string;operationId?:string;result?:Purchase};
export function readPurchaseRecovery(store:Pick<Storage,'getItem'>|null|undefined,key:string):PurchaseRecovery|null{
 try{const raw=store?.getItem(key);if(!raw)return null;const value:unknown=JSON.parse(raw);if(!isRecord(value)||typeof value.key!=='string'||(value.operationId!==undefined&&typeof value.operationId!=='string'))return null;return value as PurchaseRecovery;}catch{return null;}
}
export function writePurchaseRecovery(store:Pick<Storage,'setItem'>|null|undefined,key:string,value:PurchaseRecovery){try{store?.setItem(key,JSON.stringify(value));}catch{/* Keep the recovery state in the current component. */}}
export function priceMinorToRupees(value:string){const minor=BigInt(value);return `₹${(minor/100n).toLocaleString('en-IN')}.${(minor%100n).toString().padStart(2,'0')}`;}
export type MarketplaceApi={request:ApiRequest};
