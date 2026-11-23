import {isRecord,RequestError,errorFeedback} from './client.ts';
import type {RequestOptions} from './client.ts';

// Existing protected asset and non-login recipient identity. The active
// investor identity always comes from the authenticated backend session.
export const investorDemo={property:'f6169750-4676-4e99-887f-2bc5471bd518',issuer:'00000000-0000-4000-8000-000000000002',recipient:'00000000-0000-4000-8000-000000000005'} as const;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const tx=/^[0-9a-f]{64}$/;
const states=['PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','COMMITTED_VALID','COMMITTED_INVALID','UNKNOWN','FAILED','PAYMENT_FAILED'] as const;
export type TransferState=typeof states[number];
export type TransferCommand={asset_id:string;from_user_id:string;to_user_id:string;quantity:number;kind:'ACQUISITION'|'TRANSFER';payment_outcome:'SUCCESS'|'FAILED'};
export type TransferResult={operation_id:string;state:TransferState;transaction_id:string|null;request:TransferCommand;payment:{simulated:true;status:'NOT_EXECUTED'|'SUCCESS'|'FAILED'};commit:{transaction_id:string;code:number;block_number:number;successful:boolean}|null;ownership_confirmed:boolean;status_source:'PERSISTED_WORKFLOW';error_code:string|null};
export type Balance={schema_version:1;property_id:string;holder_id:string;quantity:number;source:'DRUNIX_EVALUATE'};
const integer=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0;
function malformed(reconcile=true):never {throw new RequestError(200,'MALFORMED_RESPONSE','The API returned inconsistent ledger evidence.',undefined,undefined,reconcile);}
export function validCommand(v:unknown):v is TransferCommand {
 return isRecord(v)&&['asset_id','from_user_id','to_user_id'].every(k=>typeof v[k]==='string'&&uuid.test(v[k] as string))&&
  v.from_user_id!==v.to_user_id&&integer(v.quantity)&&v.quantity>0&&['ACQUISITION','TRANSFER'].includes(String(v.kind))&&['SUCCESS','FAILED'].includes(String(v.payment_outcome));
}
export function sameCommand(a:TransferCommand,b:TransferCommand){return (Object.keys(a) as (keyof TransferCommand)[]).every(k=>a[k]===b[k])&&Object.keys(a).length===Object.keys(b).length;}
export function parseTransfer(v:unknown,expected:TransferCommand,operationId?:string):TransferResult {
 if(!isRecord(v)||typeof v.operation_id!=='string'||!uuid.test(v.operation_id)||(operationId&&v.operation_id!==operationId)||
  !states.includes(v.state as TransferState)||!validCommand(v.request)||!sameCommand(v.request,expected)||
  (v.transaction_id!==null&&(typeof v.transaction_id!=='string'||!tx.test(v.transaction_id)))||
  !isRecord(v.payment)||v.payment.simulated!==true||!['NOT_EXECUTED','SUCCESS','FAILED'].includes(String(v.payment.status))||
  typeof v.ownership_confirmed!=='boolean'||v.status_source!=='PERSISTED_WORKFLOW'||(v.error_code!==null&&typeof v.error_code!=='string'))return malformed();
 if(v.payment.status!=='NOT_EXECUTED'&&v.payment.status!==expected.payment_outcome)return malformed();
 const committed=v.state==='COMMITTED_VALID'||v.state==='COMMITTED_INVALID';
 if(committed){
  if(!isRecord(v.commit)||!integer(v.commit.code)||!integer(v.commit.block_number)||!v.transaction_id||v.commit.transaction_id!==v.transaction_id||
   typeof v.commit.successful!=='boolean'||v.commit.successful!==(v.commit.code===0)||v.commit.successful!==(v.state==='COMMITTED_VALID')||v.payment.status!=='SUCCESS')return malformed();
 }else if(v.commit!==null)return malformed();
 if(v.ownership_confirmed!==(v.state==='COMMITTED_VALID')||(v.state==='PAYMENT_FAILED'&&v.payment.status!=='FAILED'))return malformed();
 return v as TransferResult;
}
export function parseBalance(v:unknown,property:string,holder:string):Balance {
 if(!isRecord(v)||v.schema_version!==1||v.property_id!==property||v.holder_id!==holder||!integer(v.quantity)||v.source!=='DRUNIX_EVALUATE')return malformed(false);
 return v as Balance;
}
export function displayState(state?:TransferState){
 if(state==='COMMITTED_VALID')return 'Committed';
 if(state==='COMMITTED_INVALID'||state==='FAILED'||state==='PAYMENT_FAILED')return 'Failed';
 if(state==='UNKNOWN')return 'Unknown';
 return state==='SUBMITTED'?'Submitted':'Pending';
}
export function terminal(state?:TransferState){return ['COMMITTED_VALID','COMMITTED_INVALID','FAILED','PAYMENT_FAILED'].includes(state||'');}
export type ApiRequest=<T>(path:string,options?:RequestOptions)=>Promise<T>;
type Attempt={key:string;command:TransferCommand;operationId?:string;result?:TransferResult;uncertain:boolean};
export type FlowSnapshot={attempt:Attempt|null;busy:boolean;error:string|null;blocked:boolean};
type Store=Pick<Storage,'getItem'|'setItem'|'removeItem'>;
/** A single supervised browser session. Persist intent before dispatch, never auto-submit/retry. */
export function createTransferFlow(request:ApiRequest,store:Store,userId:string,newKey=()=>crypto.randomUUID()){
 const slot='tokansh-transfer-v1:'+userId;
 let current:FlowSnapshot={attempt:null,busy:false,error:null,blocked:false};
 try {
  const saved=store.getItem(slot);
  if(saved){
   const a=JSON.parse(saved);
   if(!isRecord(a)||typeof a.key!=='string'||!uuid.test(a.key)||!validCommand(a.command)||typeof a.uncertain!=='boolean'||(a.operationId!==undefined&&(typeof a.operationId!=='string'||!uuid.test(a.operationId))))throw new Error();
   if(a.result)a.result=parseTransfer(a.result,a.command,a.operationId as string|undefined);
   current={...current,attempt:a as Attempt};
  }
 }catch{current={...current,blocked:true,error:'Saved transfer intent could not be verified. Ask the operator to resolve it before another request.'};}
 const listeners=new Set<()=>void>();
 function publish(attempt:Attempt|null,error:string|null=null){
  current={...current,attempt,error};
  try {if(attempt)store.setItem(slot,JSON.stringify(attempt));else store.removeItem(slot);}
  catch {current={...current,blocked:true,error:'Transfer recovery storage is unavailable. Keep the displayed references and ask the operator to review.'};}
  listeners.forEach(f=>f());
 }
 function busy(value:boolean){current={...current,busy:value};listeners.forEach(f=>f());}
 function requireIdle(){if(current.busy||current.blocked)throw new RequestError(409,'OPERATION_PENDING','Resolve the current request first.');}
 const options={};
 async function observe(reconcile:boolean){
  requireIdle();const a=current.attempt;
  if(!a?.operationId)throw new RequestError(409,'RECONCILIATION_REQUIRED','Keep the request key; the operator must locate the original operation.');
  busy(true);
  try {
   const path='/api/v1/ansh/transfers/'+a.operationId+(reconcile?'/reconcile':'/status');
   const value=await request<unknown>(path,{...options,method:reconcile?'POST':'GET',correlationId:a.key});
   const result=parseTransfer(value,a.command,a.operationId);
   publish({...a,result,uncertain:!terminal(result.state)});
  }catch(error){publish(a,errorFeedback(error));throw error;}finally{busy(false);}
 }
 return {
  subscribe:(f:()=>void)=>{listeners.add(f);return ()=>{listeners.delete(f);};},getSnapshot:()=>current,
  async begin(command:TransferCommand){
   requireIdle();if(current.attempt)throw new RequestError(409,'RECONCILIATION_REQUIRED','Resolve or close the previous operation first.');
   if(!validCommand(command))throw new RequestError(422,'INVALID_REQUEST','Enter a positive whole ANSH quantity.');
   const a:Attempt={key:newKey(),command:{...command},uncertain:true};
   publish(a);if(current.blocked)throw new RequestError(503,'STORAGE_UNAVAILABLE',current.error||'Recovery storage unavailable.');
   busy(true);
   try {
    const raw=await request<unknown>('/api/v1/ansh/transfers',{...options,method:'POST',body:command,idempotencyKey:a.key,correlationId:a.key});
    const result=parseTransfer(raw,command);publish({...a,operationId:result.operation_id,result,uncertain:!terminal(result.state)});
   }catch(error){
    const id=error instanceof RequestError&&typeof error.details?.operation_id==='string'&&uuid.test(error.details.operation_id)?error.details.operation_id:undefined;
    publish({...a,operationId:id,uncertain:!(error instanceof RequestError)||error.requiresReconciliation},errorFeedback(error));throw error;
   }finally{busy(false);}
  },
  status:()=>observe(false),reconcile:()=>observe(true),
  reset(){requireIdle();if(current.attempt?.uncertain)throw new RequestError(409,'RECONCILIATION_REQUIRED','Do not replace an unresolved request.');publish(null);}
 };
}
