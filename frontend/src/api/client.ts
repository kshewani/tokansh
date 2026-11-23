export type ApiMode = 'preview' | 'real';
export type ApiConfiguration = {mode:ApiMode;baseUrl:string;configured:boolean};
export const AUTH_SESSION_KEY='tokansh-demo-auth-v1';
export type AuthRole='INVESTOR'|'LENDER';
export type AuthSession={access_token:string;token_type:'bearer';username:string;display_name:string;role:AuthRole;user_id:string;organization_id:string|null};
export type StorageLike=Pick<Storage,'getItem'|'setItem'|'removeItem'>;

function browserStorage():StorageLike|null {
 try{return typeof window==='undefined'?null:window.sessionStorage;}catch{return null;}
}
export function readAuthSession(store:StorageLike|null|undefined=browserStorage()):AuthSession|null {
 try {
  const raw=store?.getItem(AUTH_SESSION_KEY);if(!raw)return null;
  const value:unknown=JSON.parse(raw);
  if(!isRecord(value)||typeof value.access_token!=='string'||!value.access_token||value.token_type!=='bearer'||
   typeof value.username!=='string'||typeof value.display_name!=='string'||!['INVESTOR','LENDER'].includes(String(value.role))||
   typeof value.user_id!=='string'||!(value.organization_id===null||typeof value.organization_id==='string'))return null;
  return value as AuthSession;
 }catch{return null;}
}
export function writeAuthSession(value:AuthSession,store:StorageLike|null|undefined=browserStorage()):void {
 try{store?.setItem(AUTH_SESSION_KEY,JSON.stringify(value));}catch{/* React state remains authoritative for this tab. */}
}
export function clearAuthSession(store:StorageLike|null|undefined=browserStorage()):void {
 try{store?.removeItem(AUTH_SESSION_KEY);}catch{/* Session state is still cleared in React. */}
}
export function authFailure(store:StorageLike|null|undefined=browserStorage()):void {
 clearAuthSession(store);
 if(typeof window!=='undefined')window.dispatchEvent(new Event('tokansh-auth-failure'));
}

export function apiConfiguration(env:{VITE_API_MODE?:string;VITE_API_BASE_URL?:string}):ApiConfiguration {
 const mode=env.VITE_API_MODE==='real'?'real':'preview';
 const baseUrl=(env.VITE_API_BASE_URL||'').trim().replace(/\/+$/,'');
 return {mode,baseUrl,configured:mode==='real'&&baseUrl.length>0};
}

export class RequestError extends Error {
 readonly status:number;
 readonly code:string;
 readonly details?:Record<string,unknown>;
 readonly correlationId?:string;
 readonly requiresReconciliation:boolean;
 constructor(status:number,code:string,message:string,details?:Record<string,unknown>,correlationId?:string,requiresReconciliation=false){
  super(message);this.name='RequestError';this.status=status;this.code=code;
  this.details=details;this.correlationId=correlationId;this.requiresReconciliation=requiresReconciliation;
 }
}
export function isRecord(value:unknown):value is Record<string,unknown> {
 return typeof value==='object'&&value!==null&&!Array.isArray(value);
}
export function errorFeedback(error:unknown):string {
 if(!(error instanceof RequestError))return 'The request could not be completed. Your inputs have been kept.';
 const recovery=error.requiresReconciliation?'Do not resubmit. Reconcile the original operation with the backend first.':
  error.code==='OPERATION_PENDING'?'Wait for the current request to finish.':
  error.code==='BACKEND_UNAVAILABLE'?'Check the API configuration and backend availability.':
  error.code==='MALFORMED_RESPONSE'?'Ask the backend team to check the response format.':
  error.status===401||error.status===403?'Check the active backend account and permissions.':
  error.code==='NETWORK_ERROR'||error.code==='REQUEST_TIMEOUT'||error.status>=500||
  ['LEDGER_OUTCOME_UNKNOWN','RECONCILIATION_REQUIRED'].includes(error.code)?
  'For a submitted operation, check its outcome before retrying.':
  'Review the request and reported validation errors before trying again.';
 const operationId=typeof error.details?.operation_id==='string'?error.details.operation_id:null;
 return `${error.message} (${error.code}) ${recovery}${operationId?' Operation: '+operationId:''}${error.correlationId?' Reference: '+error.correlationId:''}`;
}
export type RequestOptions={method?:'GET'|'POST'|'PUT';body?:unknown;signal?:AbortSignal;idempotencyKey?:string;correlationId?:string};

/** Injectable HTTP boundary; fixtures may be supplied only by isolated tests. */
export function createRequest(config:ApiConfiguration,fetcher:typeof fetch=fetch,timeoutMs=15000,store:StorageLike|null|undefined=browserStorage()){
 return async function request<T>(path:string,opts:RequestOptions={}):Promise<T>{
  if(!config.configured)throw new RequestError(503,'BACKEND_UNAVAILABLE',
   'Python API is not configured. No backend request was sent.');
  opts.signal?.throwIfAborted();
  const method=opts.method||'GET',isWrite=method!=='GET';
  const headers:Record<string,string>={'Accept':'application/json'};
  if(opts.body!==undefined)headers['Content-Type']='application/json';
  const session=readAuthSession(store);
  if(session?.access_token)headers.Authorization=`Bearer ${session.access_token}`;
  if(opts.idempotencyKey)headers['Idempotency-Key']=opts.idempotencyKey;
  if(opts.correlationId)headers['X-Correlation-ID']=opts.correlationId;
  let body:string|undefined;
  try {body=opts.body===undefined?undefined:JSON.stringify(opts.body);}catch{
   throw new RequestError(400,'INVALID_REQUEST','The request body could not be serialized. No request was sent.');
  }
  const timeout=AbortSignal.timeout(timeoutMs);
  const signal=opts.signal?AbortSignal.any([opts.signal,timeout]):timeout;
  let correlationId=opts.correlationId;
  try {
   const res=await fetcher(config.baseUrl+path,{method,headers,credentials:'include',body,signal});
   correlationId=res.headers.get('X-Correlation-ID')||correlationId;
   let payload:unknown;
   try {payload=await res.json();}catch(error){
    if(signal.aborted)throw error;
    if(res.ok)throw new RequestError(res.status,'MALFORMED_RESPONSE','The API returned invalid JSON.',undefined,correlationId,isWrite);
   }
   correlationId=isRecord(payload)&&isRecord(payload.meta)&&typeof payload.meta.correlation_id==='string'?
    payload.meta.correlation_id:correlationId;
   if(!res.ok){
    const err=isRecord(payload)&&isRecord(payload.error)?payload.error:{};
    if(res.status===401)authFailure(store);
    throw new RequestError(res.status,typeof err.code==='string'?err.code:'HTTP_ERROR',
     typeof err.message==='string'?err.message:`API request failed (HTTP ${res.status}).`,
     isRecord(err.details)?err.details:undefined,correlationId,isWrite&&(res.status>=500||res.status===408||
      ['LEDGER_OUTCOME_UNKNOWN','RECONCILIATION_REQUIRED','IDEMPOTENCY_CONFLICT','LEDGER_SUBMISSION_FAILED','LEDGER_COMMIT_FAILED'].includes(String(err.code))));
   }
   if(!isRecord(payload)||!('data' in payload)||payload.data==null)
    throw new RequestError(res.status,'MALFORMED_RESPONSE','The API response is missing its data payload.',undefined,correlationId);
   return payload.data as T;
  }catch(error){
   if(opts.signal?.aborted){
    if(!isWrite)throw error;
    throw new RequestError(0,'REQUEST_CANCELLED','Waiting was cancelled; this does not cancel a submitted backend operation.',undefined,correlationId,true);
   }
   if(timeout.aborted)throw new RequestError(0,'REQUEST_TIMEOUT','The API response timed out; the operation outcome may be unknown.',undefined,correlationId,isWrite);
   if(error instanceof RequestError){
    if(isWrite&&error.code==='MALFORMED_RESPONSE')throw new RequestError(error.status,error.code,error.message,error.details,correlationId,true);
    throw error;
   }
   throw new RequestError(0,'NETWORK_ERROR','The API could not be reached; the operation outcome may be unknown.',undefined,correlationId,isWrite);
  }
 };
}
