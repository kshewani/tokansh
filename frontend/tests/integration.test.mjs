import test from 'node:test';
import assert from 'node:assert/strict';
import {QueryClient,MutationObserver,QueryObserver} from '@tanstack/react-query';
import {apiConfiguration,createRequest,RequestError,errorFeedback} from '../src/api/client.ts';
import {parseSystemStatus,componentStatus} from '../src/api/systemStatus.ts';
import {previewData,screenIntegrated,submitAction,confirmReview,createSubmissionGuard,checkSubmissionResult} from '../src/app/integration.ts';
import {phases} from '../src/demo/scenario.ts';

const config=apiConfiguration({VITE_API_MODE:'real',VITE_API_BASE_URL:'https://api.example.test/'});
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const unavailable={components:[{name:'FastAPI',status:'CONNECTED'},{name:'Go gateway',status:'UNAVAILABLE'}]};

test('mode selection preserves preview default and never falls back when a real API URL is missing',async()=>{
 assert.deepEqual(apiConfiguration({}),{mode:'preview',baseUrl:'',configured:false});
 assert.equal(apiConfiguration({VITE_API_BASE_URL:'https://api.example.test'}).mode,'preview');
 const missing=apiConfiguration({VITE_API_MODE:'real',VITE_API_BASE_URL:'  '});
 assert.equal(missing.mode,'real');assert.equal(missing.configured,false);
 let called=false;
 const request=createRequest(missing,async()=>{called=true;return json({data:unavailable});});
 await assert.rejects(request('/api/v1/system/status'),{code:'BACKEND_UNAVAILABLE'});
 assert.equal(called,false);
});
test('connected mode has no preview holdings or history at any scenario phase',()=>{
 for(const phase of phases){
  assert.equal(previewData('real',phase.id),null);
  assert.ok(previewData('preview',phase.id));
 }
 for(const path of ['/registry','/issuance','/transactions','/collateral','/lending','/distributions','/audit','/intelligence','/future-screen']){
  assert.equal(screenIntegrated('real',path),false);
  assert.equal(screenIntegrated('preview',path),true);
 }
 for(const path of ['/overview','/marketplace','/portfolio'])assert.equal(screenIntegrated('real',path),true);
 assert.equal(screenIntegrated('real','/system'),true);
 assert.equal(screenIntegrated('real','/System/'),true);
 assert.equal(screenIntegrated('real','/system/history'),false);
});
test('status HTTP 200 preserves actual unavailable components without inferring ledger readiness',async()=>{
 const request=createRequest(config,async(url,options)=>{
  assert.equal(url,'https://api.example.test/api/v1/system/status');
  assert.equal(options.credentials,'include');
  return json({data:unavailable});
 });
 const status=parseSystemStatus(await request('/api/v1/system/status'));
 assert.equal(componentStatus(status,'FastAPI'),'CONNECTED');
 assert.equal(componentStatus(status,'Go gateway'),'UNAVAILABLE');
 assert.equal(componentStatus(status,'DRUNIX peers'),'UNKNOWN');
 assert.equal(status.last_ledger_operation,undefined);
});
test('status parser accepts empty observations and preserves only a returned last-operation reference',()=>{
 assert.equal(componentStatus(parseSystemStatus({components:[]}),'FastAPI'),'UNKNOWN');
 assert.equal(parseSystemStatus({components:[],last_ledger_operation:null}).last_ledger_operation,null);
 assert.equal(parseSystemStatus({components:[],last_ledger_operation:'returned-reference'}).last_ledger_operation,'returned-reference');
});
test('status parser rejects malformed values, duplicate components and unsupported readiness labels',()=>{
 for(const value of [null,[],{}, {components:{}},{components:[null]},
  {components:[{name:'FastAPI',status:'healthy'}]},
  {components:[{name:'',status:'CONNECTED'}]},
  {components:[{name:'FastAPI',status:'CONNECTED',detail:42}]},
  {components:[{name:'FastAPI',status:'CONNECTED'},{name:' fastapi ',status:'UNAVAILABLE'}]},
  {components:[],last_ledger_operation:{status:'COMMITTED'}}]){
  assert.throws(()=>parseSystemStatus(value),{code:'MALFORMED_RESPONSE'});
 }
});
test('successful HTTP with invalid JSON or a missing data envelope is not accepted',async()=>{
 for(const response of [new Response('<html>proxy error</html>'),json({}),json({data:null}),json([])]){
  await assert.rejects(createRequest(config,async()=>response)('/status'),{code:'MALFORMED_RESPONSE'});
 }
});
test('structured API failures retain code, details and correlation reference',async()=>{
 const request=createRequest(config,async()=>json({error:{code:'INVALID_REQUEST',message:'Quantity must be positive.',details:{quantity:0}},meta:{correlation_id:'request-42'}},422));
 await assert.rejects(request('/orders',{method:'POST',body:{quantity:0},idempotencyKey:'same-operation'}),error=>{
  assert.equal(error.status,422);assert.equal(error.code,'INVALID_REQUEST');
  assert.deepEqual(error.details,{quantity:0});assert.equal(error.correlationId,'request-42');
  assert.match(errorFeedback(error),/Review the request/);assert.match(errorFeedback(error),/request-42/);
  return true;
 });
});
test('non-JSON API failure preserves HTTP failure and provides actionable feedback',async()=>{
 const request=createRequest(config,async()=>new Response('Bad gateway',{status:502}));
 await assert.rejects(request('/status'),error=>{
  assert.equal(error.status,502);assert.equal(error.code,'HTTP_ERROR');
  assert.match(errorFeedback(error),/check its outcome before retrying/);return true;
 });
});
test('network failure propagates without an automatic mutation retry',async()=>{
 let calls=0;
 const request=createRequest(config,async()=>{calls++;throw new TypeError('fetch failed');});
 await assert.rejects(request('/orders',{method:'POST',body:{}}),{code:'NETWORK_ERROR'});
 assert.equal(calls,1);
});
test('timeouts and caller cancellation are distinguished',async()=>{
 const pending=async(_url,{signal})=>new Promise((_resolve,reject)=>{
  if(signal.aborted)reject(signal.reason);
  else signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
 });
 // AbortSignal.timeout does not keep Node alive on its own.
 const keepAlive=setTimeout(()=>{},1000);
 try {
  await assert.rejects(createRequest(config,pending,5)('/status'),{code:'REQUEST_TIMEOUT'});
  const controller=new AbortController();controller.abort();
  await assert.rejects(createRequest(config,pending)('/status',{signal:controller.signal}),{name:'AbortError'});
 }finally{clearTimeout(keepAlive);}
});
test('status query can recover from a malformed response by explicitly refetching',async()=>{
 let calls=0;
 const request=createRequest(config,async()=>json({data:++calls===1?{}:unavailable}));
 const client=new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}});
 const observer=new QueryObserver(client,{queryKey:['status'],queryFn:async()=>parseSystemStatus(await request('/status')),enabled:false});
 try {
  const failed=await observer.refetch();assert.equal(failed.error.code,'MALFORMED_RESPONSE');
  const recovered=await observer.refetch();assert.equal(recovered.status,'success');
  assert.equal(componentStatus(recovered.data,'Go gateway'),'UNAVAILABLE');assert.equal(calls,2);
 }finally{observer.destroy();client.clear();}
});
test('mutation failure reaches the review boundary and does not execute the close or clear-input path',async()=>{
 let requests=0;
 const request=createRequest(config,async()=>{requests++;return json({error:{code:'LEDGER_UNAVAILABLE',message:'Gateway unavailable.'}},503);});
 const client=new QueryClient({defaultOptions:{mutations:{retry:false,gcTime:0}}});
 const mutation=new MutationObserver(client,{mutationFn:()=>request('/existing-operation',{method:'POST',body:{quantity:500}})});
 let open=true,input='500',reported;
 const guard=createSubmissionGuard();
 try {
  await assert.rejects(submitAction('real',()=>guard.run(()=>mutation.mutate()),()=>assert.fail('No preview fallback')),{code:'LEDGER_UNAVAILABLE'});
  await confirmReview(async()=>{
   await submitAction('real',()=>guard.run(()=>mutation.mutate()),()=>assert.fail('No preview fallback'));
   open=false;input='';
  },error=>{reported=error;});
  assert.equal(open,true);assert.equal(input,'500');assert.equal(reported.code,'RECONCILIATION_REQUIRED');
  assert.equal(requests,1);
  assert.equal(mutation.getCurrentResult().isError,true);
 }finally{client.clear();}
});
test('rapid repeated submissions send exactly one request before any pending render',async()=>{
 const guard=createSubmissionGuard();
 let finish,calls=0;
 const request=createRequest(config,async()=>{calls++;return new Promise(resolve=>{finish=resolve;});});
 const first=guard.run(()=>request('/operation',{method:'POST',body:{}}));
 assert.equal(guard.pending,true);
 const repeated=Array.from({length:10},()=>guard.run(()=>request('/operation',{method:'POST',body:{}})));
 const results=await Promise.allSettled(repeated);
 assert.ok(results.every(result=>result.status==='rejected'&&result.reason.code==='OPERATION_PENDING'));
 assert.equal(calls,1);
 finish(json({data:{status:'COMMITTED'}}));await first;
 assert.equal(guard.pending,false);assert.equal(guard.blocked,false);
});
test('definitive validation rejection unlocks the guard and preserves inputs for correction',async()=>{
 const guard=createSubmissionGuard();
 const input={quantity:0};
 await assert.rejects(guard.run(()=>Promise.reject(new RequestError(422,'INVALID_REQUEST','Quantity is invalid.'))));
 assert.equal(guard.pending,false);assert.equal(guard.blocked,false);
 assert.deepEqual(input,{quantity:0});
 input.quantity=500;
 assert.equal(await guard.run(()=>input.quantity),500);
});
test('synchronous handler failure releases the pending latch and reaches the review error boundary',async()=>{
 const guard=createSubmissionGuard();let error,closed=false;
 await confirmReview(async()=>{await guard.run(()=>{throw new Error('unexpected');});closed=true;},value=>{error=value;});
 assert.equal(error.message,'unexpected');assert.equal(closed,false);assert.equal(guard.pending,false);
});
test('failed HTTP 200 operation statuses do not run the success path',async()=>{
 for(const status of ['FAILED','REJECTED','PAYMENT_FAILED','CANCELLED']){
  let closed=false,error;
  const guard=createSubmissionGuard();
  const request=createRequest(config,async()=>json({data:{status,operation_id:'original-operation'}}));
  await confirmReview(async()=>{
   await guard.run(async()=>checkSubmissionResult(await request('/operation',{method:'POST',body:{}}),'correlation-key'));closed=true;
  },value=>{error=value;});
  assert.equal(closed,false);assert.equal(error.code,'OPERATION_FAILED');
  assert.equal(error.details.operation_id,'original-operation');
  assert.equal(guard.blocked,true);
 }
});
test('an idempotency conflict cannot be bypassed by resubmitting with a fresh key',async()=>{
 let calls=0;
 const request=createRequest(config,async()=>{calls++;return json({error:{code:'IDEMPOTENCY_CONFLICT',message:'Existing operation conflicts.'}},409);});
 const guard=createSubmissionGuard();
 await assert.rejects(guard.run(()=>request('/operation',{method:'POST',body:{},idempotencyKey:'original-key'})),{code:'IDEMPOTENCY_CONFLICT',requiresReconciliation:true});
 await assert.rejects(guard.run(()=>request('/operation',{method:'POST',body:{},idempotencyKey:'new-key'})),{code:'RECONCILIATION_REQUIRED'});
 assert.equal(calls,1);
});
test('pending, unknown and unsupported outcomes block further submission and preserve original references',async()=>{
 for(const value of [{},null,{status:'unexpected'},...['CREATED','VALIDATING','SUBMITTED','UNKNOWN','RECONCILIATION_REQUIRED'].map(status=>({status,operation_id:'original-operation'}))]){
  const guard=createSubmissionGuard();let sent=0;
  await assert.rejects(guard.run(()=>{sent++;checkSubmissionResult(value,'original-correlation');}),error=>error.requiresReconciliation);
  assert.equal(guard.blocked,true);
  await assert.rejects(guard.run(()=>{sent++;}),{code:'RECONCILIATION_REQUIRED',correlationId:'original-correlation'});
  assert.equal(sent,1);
 }
});
test('correlation and idempotency headers are forwarded unchanged, and error metadata is retained',async()=>{
 const request=createRequest(config,async(_url,{headers})=>{
  assert.equal(headers['X-Correlation-ID'],'client-correlation');
  assert.equal(headers['Idempotency-Key'],'original-key');
  return new Response('not json',{status:502,headers:{'X-Correlation-ID':'server-correlation'}});
 });
 await assert.rejects(request('/operation',{method:'POST',body:{},idempotencyKey:'original-key',correlationId:'client-correlation'}),error=>{
  assert.equal(error.correlationId,'server-correlation');assert.equal(error.requiresReconciliation,true);
  assert.match(errorFeedback(error),/Do not resubmit/);return true;
 });
});
test('invalid JSON preserves the response correlation header even for read-only requests',async()=>{
 const request=createRequest(config,async()=>new Response('<html/>',{headers:{'X-Correlation-ID':'invalid-json-reference'}}));
 await assert.rejects(request('/status'),{code:'MALFORMED_RESPONSE',correlationId:'invalid-json-reference',requiresReconciliation:false});
});
test('write cancellation after dispatch is unresolved and cannot be mistaken for cancelling the backend operation',async()=>{
 const controller=new AbortController();let dispatched=0;
 const request=createRequest(config,async(_url,{signal})=>{
  dispatched++;
  return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
 });
 const guard=createSubmissionGuard();
 const pending=guard.run(()=>request('/operation',{method:'POST',body:{},signal:controller.signal,correlationId:'cancelled-reference'}));
 controller.abort();
 await assert.rejects(pending,{code:'REQUEST_CANCELLED',requiresReconciliation:true,correlationId:'cancelled-reference'});
 await assert.rejects(guard.run(()=>request('/operation',{method:'POST',body:{}})),{code:'RECONCILIATION_REQUIRED'});
 assert.equal(dispatched,1);
});
test('pre-dispatch cancellation never calls fetch and leaves no unresolved operation',async()=>{
 const controller=new AbortController();controller.abort();let sent=0;
 const request=createRequest(config,async()=>{sent++;return json({data:{}});});
 const guard=createSubmissionGuard();
 await assert.rejects(guard.run(()=>request('/operation',{method:'POST',body:{},signal:controller.signal})),{name:'AbortError'});
 assert.equal(sent,0);assert.equal(guard.blocked,false);
});
test('read cancellation after dispatch is preserved for query cancellation',async()=>{
 const controller=new AbortController();
 const request=createRequest(config,async(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true})));
 const pending=request('/status',{signal:controller.signal});controller.abort();
 await assert.rejects(pending,{name:'AbortError'});
});
test('write timeouts and malformed successful responses are unresolved and prevent resubmission',async()=>{
 const keepAlive=setTimeout(()=>{},1000);
 try {
  for(const fetcher of [async()=>json({}),async()=>new Response('not json'),
   async(_url,{signal})=>new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}))]){
   const request=createRequest(config,fetcher,5),guard=createSubmissionGuard();
   await assert.rejects(guard.run(()=>request('/operation',{method:'POST',body:{},correlationId:'original-reference'})),error=>error.requiresReconciliation);
   assert.equal(guard.pending,false);assert.equal(guard.blocked,true);
  }
 }finally{clearTimeout(keepAlive);}
});
test('local serialization failure sends nothing and is safe to correct',async()=>{
 let sent=0;const body={};body.self=body;
 const request=createRequest(config,async()=>{sent++;return json({data:{}});});
 await assert.rejects(request('/operation',{method:'POST',body}),{code:'INVALID_REQUEST',requiresReconciliation:false});
 assert.equal(sent,0);
});
test('preview submissions retain the existing notice-only behavior',async()=>{
 let notices=0;
 await submitAction('preview',()=>assert.fail('Preview must never send a mutation'),()=>{notices++;});
 assert.equal(notices,1);
});
test('request forwards body and operation idempotency header unchanged',async()=>{
 const request=createRequest(config,async(_url,options)=>{
  assert.equal(options.headers['Idempotency-Key'],'operation-key');
  assert.equal(options.body,'{"quantity":500}');
  return json({data:{status:'SUBMITTED'}});
 });
 assert.deepEqual(await request('/operation',{method:'POST',body:{quantity:500},idempotencyKey:'operation-key'}),{status:'SUBMITTED'});
 assert.match(errorFeedback(new RequestError(403,'INSUFFICIENT_PERMISSIONS','Forbidden')),/permissions/);
});
