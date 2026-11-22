import type {ApiMode} from '../api/client.ts';
import {isRecord,RequestError} from '../api/client.ts';
import type {Phase} from '../demo/scenario.ts';
import {scenarioProperty,scenarioHoldings,scenarioEvents,scenarioEntitlement} from '../demo/scenario.ts';

export function previewData(mode:ApiMode,phase:Phase){
 if(mode!=='preview')return null;
 return {property:scenarioProperty(phase),holding:scenarioHoldings(phase),
  events:scenarioEvents(phase),entitlement:scenarioEntitlement(phase)};
}
export function screenIntegrated(mode:ApiMode,path:string):boolean {
 return mode==='preview'||['/wallet','/properties','/transactions','/system','/overview','/marketplace','/portfolio','/collateral','/lending','/distributions','/intelligence'].includes(path.replace(/\/+$/,'').toLowerCase());
}
/** Synchronous latch: React's pending render alone cannot guard rapid clicks. */
export function createSubmissionGuard(){
 let pending=false;
 let unresolved:RequestError|null=null;
 return {
  get pending(){return pending;},
  get blocked(){return unresolved!==null;},
  async run<T>(action:()=>Promise<T>|T):Promise<T>{
   if(pending)throw new RequestError(409,'OPERATION_PENDING','A request is already in progress.');
   if(unresolved)throw new RequestError(409,'RECONCILIATION_REQUIRED','An earlier operation has not been resolved.',unresolved.details,unresolved.correlationId,true);
   pending=true;
   try {return await action();}catch(error){
    if(error instanceof RequestError&&error.requiresReconciliation)unresolved=error;
    throw error;
   }finally{pending=false;}
  }
 };
}
/** HTTP success alone must not run a form's success/close path. */
export function checkSubmissionResult(value:unknown,correlationId:string):void {
 const details=isRecord(value)&&typeof value.operation_id==='string'?{operation_id:value.operation_id}:undefined;
 if(!isRecord(value)||typeof value.status!=='string'||!value.status.trim())
  throw new RequestError(200,'MALFORMED_RESPONSE','The mutation response has no explicit operation status.',details,correlationId,true);
 const status=value.status;
 // A generic FAILED result does not establish whether payment/other effects need compensation.
 if(['FAILED','REJECTED','PAYMENT_FAILED','CANCELLED'].includes(status))
  throw new RequestError(409,'OPERATION_FAILED',`Backend reports ${status}; the request was not confirmed successful.`,details,correlationId,true);
 if(['CREATED','VALIDATING','PENDING','PROCESSING','SUBMITTED','UNKNOWN','RECONCILIATION_REQUIRED'].includes(status))
  throw new RequestError(409,'RECONCILIATION_REQUIRED',`Backend reports ${status}; resolve the original operation before submitting again.`,details,correlationId,true);
 // These are existing documented application states, not proof of ledger state.
 if(!['DRAFT','APPROVED','DECLARED','COMMITTED','COMPLETED','SUCCESS','success','REPAID','ACTIVE','RELEASED'].includes(status))
  throw new RequestError(200,'MALFORMED_RESPONSE','The mutation response has an unsupported operation status.',details,correlationId,true);
}
export async function submitAction(mode:ApiMode,mutate:()=>Promise<unknown>,onPreview:()=>void):Promise<void> {
 if(mode==='preview'){onPreview();return;}
 // Keep rejection intact so callers never execute their success/close path.
 await mutate();
}
/** React event boundary: report rejected confirmations without unhandled promises. */
export async function confirmReview(action:()=>void|Promise<void>,reportError:(error:unknown)=>void):Promise<void> {
 try {await action();}catch(error){reportError(error);}
}
