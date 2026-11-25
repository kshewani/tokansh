import test from 'node:test';
import assert from 'node:assert/strict';
import {isDemoRole,readDemoSession,writeDemoSession,clearDemoSession,DEMO_SESSION_KEY} from '../src/lib/session.ts';

function fakeSession(initial={}){
 const data=new Map(Object.entries(initial));
 return {getItem(k){return data.has(k)?data.get(k):null;},setItem(k,v){data.set(k,String(v));},removeItem(k){data.delete(k);}};
}
const aarav={role:'INVESTOR',userId:'u-aarav',name:'Aarav',username:'aarav',token:'t-123'};
test('only the three demo roles are accepted',()=>{
 for(const role of ['ISSUER','INVESTOR','LENDER'])assert.equal(isDemoRole(role),true);
 for(const value of ['ADMIN','DEMO','',null,undefined,42])assert.equal(isDemoRole(value),false);
});
test('fresh visitor has no demo session',()=>assert.equal(readDemoSession(fakeSession()),null));
test('login stores role and backend user id; reload restores it',()=>{
 const store=fakeSession();writeDemoSession(aarav,store);
 assert.deepEqual(readDemoSession(store),aarav);
});
test('logout clears the session',()=>{
 const store=fakeSession();writeDemoSession(aarav,store);clearDemoSession(store);
 assert.equal(readDemoSession(store),null);
});
test('stale, malformed or role-less sessions are rejected',()=>{
 assert.equal(readDemoSession(fakeSession({[DEMO_SESSION_KEY]:'INVESTOR'})),null);
 assert.equal(readDemoSession(fakeSession({[DEMO_SESSION_KEY]:JSON.stringify({role:'GUEST',userId:'x',name:'x'})})),null);
 assert.equal(readDemoSession(fakeSession({[DEMO_SESSION_KEY]:JSON.stringify({role:'LENDER',name:'x'})})),null);
});
test('storage failures do not throw or fabricate a session',()=>{
 const broken={getItem(){throw Error('blocked');},setItem(){throw Error('blocked');},removeItem(){throw Error('blocked');}};
 assert.equal(readDemoSession(broken),null);
 assert.doesNotThrow(()=>writeDemoSession(aarav,broken));
 assert.doesNotThrow(()=>clearDemoSession(broken));
});
test('a stored session without its bearer token is rejected',()=>{
 const store=fakeSession({[DEMO_SESSION_KEY]:JSON.stringify({role:'INVESTOR',userId:'u',name:'A',username:'aarav'})});
 assert.equal(readDemoSession(store),null);
});
