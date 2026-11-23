import test from 'node:test';
import assert from 'node:assert/strict';
import {authFailure,createRequest,readAuthSession} from '../src/api/client.ts';
import {currentSession,login,logout,parseAuthSession} from '../src/api/auth.ts';

const aarav='00000000-0000-4000-8000-000000000003';
const meera='00000000-0000-4000-8000-000000000006';
const token='opaque-demo-token';
const response=(data,status=200)=>new Response(JSON.stringify({data,meta:{correlation_id:'auth-test'}}),{status,headers:{'Content-Type':'application/json'}});
const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};
const session=(user_id=meera,role='INVESTOR',organization_id=null)=>({access_token:token,token_type:'bearer',username:role==='LENDER'?'axim-bank':user_id===aarav?'Aarav':'Meera',display_name:role==='LENDER'?'Axim Bank':user_id===aarav?'Aarav':'Meera',role,user_id,organization_id});

test('login posts the selected identity and accepts the backend bearer session',async()=>{
 const calls=[];
 const value=await login(async(path,options)=>{calls.push({path,options});return session();},'MeErA','anything','INVESTOR');
 assert.equal(value.user_id,meera);assert.equal(calls[0].path,'/api/v1/auth/login');
 assert.deepEqual(calls[0].options.body,{username:'MeErA',password:'anything'});
});

test('invalid credentials and role mismatches fail closed',async()=>{
 await assert.rejects(login(async()=>{throw Object.assign(new Error('invalid'),{status:401});},'unknown','x','INVESTOR'));
 await assert.rejects(login(async()=>session('00000000-0000-4000-8000-000000000004','LENDER','axim-bank'),'Meera','x','INVESTOR'),{code:'INVALID_CREDENTIALS'});
 assert.throws(()=>parseAuthSession({...session(),user_id:'not-a-uuid'}),{code:'MALFORMED_RESPONSE'});
});

test('restored sessions call /me with the stored bearer and logout invalidates it',async()=>{
 const calls=[];
 const value=await currentSession(async(path,options)=>{calls.push({path,options});return {...session(),access_token:undefined};},token);
 assert.equal(value.access_token,token);assert.equal(calls[0].path,'/api/v1/auth/me');
 await logout(async(path,options)=>{calls.push({path,options});return {logged_out:true};});
 assert.equal(calls[1].path,'/api/v1/auth/logout');assert.equal(calls[1].options.method,'POST');
});

test('protected requests use only the opaque bearer and clear the session after 401',async()=>{
 const store=storage();store.setItem('tokansh-demo-auth-v1',JSON.stringify(session()));
 const request=createRequest({mode:'real',baseUrl:'https://mock.invalid',configured:true},async(url,options)=>{
  assert.equal(url,'https://mock.invalid/api/v1/ansh/balances/property/'+meera);
  assert.equal(options.headers.Authorization,'Bearer '+token);assert.equal(options.headers['X-Demo-Role'],undefined);
  return response({schema_version:1});
 },15000,store);
 assert.deepEqual(await request('/api/v1/ansh/balances/property/'+meera),{schema_version:1});
 assert.deepEqual(readAuthSession(store),session());
 const expired=new Response(JSON.stringify({error:{code:'INVALID_SESSION',message:'expired'}}),{status:401,headers:{'Content-Type':'application/json'}});
 await assert.rejects(createRequest({mode:'real',baseUrl:'https://mock.invalid',configured:true},async()=>expired,15000,store),error=>error.status===401&&error.code==='INVALID_SESSION');
 assert.equal(readAuthSession(store),null);
});

test('explicit auth failure clears local state without persisting a replacement identity',()=>{
 const store=storage();store.setItem('tokansh-demo-auth-v1',JSON.stringify(session(aarav)));
 authFailure(store);assert.equal(readAuthSession(store),null);
});
