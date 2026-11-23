import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequest,RequestError} from '../src/api/client.ts';
import {createTransferFlow,parseTransfer,parseBalance,displayState,investorDemo as ids} from '../src/api/transfers.ts';
const aarav='00000000-0000-4000-8000-000000000003';
const op='70000000-0000-4000-8000-000000000001',key='80000000-0000-4000-8000-000000000001';
const command={asset_id:ids.property,from_user_id:ids.issuer,to_user_id:aarav,quantity:4,kind:'ACQUISITION',payment_outcome:'SUCCESS'};
function result(state='COMMITTED_VALID',request=command){
 const done=['COMMITTED_VALID','COMMITTED_INVALID'].includes(state),valid=state==='COMMITTED_VALID';
 return {operation_id:op,state,transaction_id:'a'.repeat(64),request:{...request},payment:{simulated:true,status:state==='PAYMENT_FAILED'?'FAILED':'SUCCESS'},commit:done?{transaction_id:'a'.repeat(64),code:valid?0:11,block_number:42,successful:valid}:null,ownership_confirmed:valid,status_source:'PERSISTED_WORKFLOW',error_code:null};
}
function storage(){const values=new Map();return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)};}
const response=(data,status=200)=>new Response(JSON.stringify({data,meta:{correlation_id:'test-only-reference'}}),{status,headers:{'Content-Type':'application/json'}});

test('only matching confirmed valid commit evidence can establish success',()=>{
 assert.equal(parseTransfer(result(),command).ownership_confirmed,true);
 for(const state of ['PREPARING','PREPARED','SUBMISSION_PENDING','SUBMITTED','UNKNOWN','FAILED','COMMITTED_INVALID']){
  assert.equal(parseTransfer(result(state),command).ownership_confirmed,false);
 }
 for(const bad of [{...result(),commit:null},{...result(),commit:{...result().commit,successful:false}},
  {...result(),transaction_id:'invented'}, {...result(),operation_id:'missing'},
  {...result(),request:{...command,quantity:5}}, {...result('UNKNOWN'),ownership_confirmed:true},
  {...result(),payment:{simulated:false,status:'SUCCESS'}},{...result(),state:'COMMITTED'}]){
  assert.throws(()=>parseTransfer(bad,command),{code:'MALFORMED_RESPONSE'});
 }
 const failedPayment={...command,payment_outcome:'FAILED'};
 assert.equal(parseTransfer(result('PAYMENT_FAILED',failedPayment),failedPayment).ownership_confirmed,false);
 assert.throws(()=>parseTransfer(result('PAYMENT_FAILED'),command),{code:'MALFORMED_RESPONSE'});
 assert.equal(displayState('SUBMITTED'),'Submitted');assert.equal(displayState('UNKNOWN'),'Unknown');
 assert.equal(displayState('COMMITTED_VALID'),'Committed');assert.equal(displayState('COMMITTED_INVALID'),'Failed');
});
test('API sends stable key without the removed role header or transfer secrets',async()=>{
 const request=createRequest({mode:'real',baseUrl:'https://mock.invalid',configured:true},async(_url,opts)=>{
  assert.equal(opts.headers['X-Demo-Role'],undefined);assert.equal(opts.headers['Idempotency-Key'],key);
  assert.equal(opts.headers.Authorization,undefined);assert.equal(opts.headers['X-Operator-Capability'],undefined);
  return response(result());
 });
 const flow=createTransferFlow(request,storage(),aarav,()=>key);
 await flow.begin(command);assert.equal(flow.getSnapshot().attempt.result.state,'COMMITTED_VALID');
});
test('rapid repeat clicks and pending reload never prepare or submit a second request',async()=>{
 const store=storage();let release,sends=0;
 const request=async(path,opts)=>{
  sends++;
  assert.equal(JSON.parse(store.getItem('tokansh-transfer-v1:'+aarav)).key,key);
  assert.equal(opts.idempotencyKey,key);
  return new Promise(resolve=>{release=resolve;});
 };
 const flow=createTransferFlow(request,store,aarav,()=>key);
 const pending=flow.begin(command);
 await assert.rejects(flow.begin(command),{code:'OPERATION_PENDING'});
 release(result('UNKNOWN'));await pending;
 assert.equal(sends,1);assert.throws(()=>flow.reset(),{code:'RECONCILIATION_REQUIRED'});
 const restored=createTransferFlow(request,store,aarav,()=>assert.fail('No new key while unresolved'));
 await assert.rejects(restored.begin(command),{code:'RECONCILIATION_REQUIRED'});
 assert.equal(sends,1);
});
test('UNKNOWN reconciles only the original operation; terminal evidence permits an explicit new intent',async()=>{
 const paths=[];
 const flow=createTransferFlow(async(path,opts)=>{
  paths.push([path,opts.method]);
  if(paths.length===1)return result('UNKNOWN');
  assert.equal(path,`/api/v1/ansh/transfers/${op}/reconcile`);assert.equal(opts.method,'POST');
  assert.equal(opts.body,undefined);assert.equal(opts.idempotencyKey,undefined);
  return result();
 },storage(),aarav,()=>key);
 await flow.begin(command);await flow.reconcile();
 assert.equal(flow.getSnapshot().attempt.result.state,'COMMITTED_VALID');assert.equal(paths.length,2);
 flow.reset();assert.equal(flow.getSnapshot().attempt,null);
});
test('lost responses retain the key and block fresh submission; errors retain inputs',async()=>{
 const store=storage();let calls=0;
 const request=async()=>{calls++;throw new RequestError(0,'NETWORK_ERROR','Test-only lost response',undefined,undefined,true);};
 const flow=createTransferFlow(request,store,aarav,()=>key);
 await assert.rejects(flow.begin(command));
 assert.deepEqual(flow.getSnapshot().attempt.command,command);
 const restored=createTransferFlow(request,store,aarav);
 await assert.rejects(restored.begin(command));await assert.rejects(restored.reconcile());
 assert.equal(calls,1);assert.equal(restored.getSnapshot().attempt.key,key);
});
test('failed payment and balance errors cannot become ownership success',async()=>{
 const flow=createTransferFlow(async()=>result('PAYMENT_FAILED',{...command,payment_outcome:'FAILED'}),storage(),aarav,()=>key);
 await flow.begin({...command,payment_outcome:'FAILED'});
 assert.equal(flow.getSnapshot().attempt.result.ownership_confirmed,false);flow.reset();
 const blocked=createTransferFlow(async()=>{throw new RequestError(409,'INSUFFICIENT_BALANCE','Test-only insufficient balance',{operation_id:op});},storage(),aarav,()=>key);
 await assert.rejects(blocked.begin(command));assert.equal(blocked.getSnapshot().attempt.operationId,op);
 assert.deepEqual(blocked.getSnapshot().attempt.command,command);assert.match(blocked.getSnapshot().error,/INSUFFICIENT_BALANCE/);
});
test('balances never default to initial inventory; identities, precision and source must match',()=>{
 const value={schema_version:1,property_id:ids.property,holder_id:aarav,quantity:3,source:'DRUNIX_EVALUATE'};
 assert.equal(parseBalance(value,ids.property,aarav).quantity,3);
 for(const v of [null,{}, {...value,quantity:-1},{...value,quantity:1.5},{...value,quantity:9007199254740992},{...value,holder_id:ids.issuer},{...value,source:'UI_PREVIEW'}]){
  assert.throws(()=>parseBalance(v,ids.property,aarav),{code:'MALFORMED_RESPONSE'});
 }
});
test('acquisition then secondary transfer use distinct reviewed commands and explicit intents',async()=>{
 const commands=[];let n=0;
 const flow=createTransferFlow(async(_path,opts)=>{commands.push(opts.body);return result('COMMITTED_VALID',opts.body);},storage(),aarav,()=>n++?op:key);
 await flow.begin(command);flow.reset();
 const secondary={...command,from_user_id:aarav,to_user_id:ids.recipient,quantity:1,kind:'TRANSFER'};
 await flow.begin(secondary);
 assert.equal(commands[0].quantity,4);assert.equal(commands[1].quantity,1);
 assert.equal(commands[0].to_user_id,commands[1].from_user_id);
});
