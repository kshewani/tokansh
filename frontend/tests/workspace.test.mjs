import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceRoles,landing,loanActions,readInstitution} from '../src/app/workspace.ts';
import {parseLenders,parseCash,parseEntry,createCashFlow} from '../src/api/demoFinance.ts';
import {RequestError} from '../src/api/client.ts';
const entry={id:'cash-1',kind:'DEMO_FUNDS',amount_minor:'100',balance_after_minor:'100',loan_id:null,created_at:'2026-11-21T10:00:00Z',currency:'INR',simulated:true,status:'SIMULATED_COMPLETED'};
function storage(){const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)};}
test('two login workspaces, distinct landing pages and state-specific decisions',()=>{
 assert.deepEqual(workspaceRoles.map(r=>r.role),['INVESTOR','LENDER']);
 assert.equal(landing('INVESTOR'),'/overview');assert.equal(landing('LENDER'),'/lending');
 for(const state of ['APPLIED','ASSESSED','APPROVED'])assert.deepEqual(loanActions('INVESTOR',state),[]);
 assert.deepEqual(loanActions('LENDER','ASSESSED'),['approve','reject']);assert.deepEqual(loanActions('LENDER','DISBURSED'),[]);
 assert.deepEqual(loanActions('INVESTOR','DISBURSED'),['repay']);assert.deepEqual(loanActions('INVESTOR','REPAID'),['release']);
});
test('institution preference survives reload; catalogue rejects malformed or duplicate offers',()=>{
 const store=storage();assert.equal(readInstitution(store),'axim-bank');store.setItem('tokansh-lender','real-finance');assert.equal(readInstitution(store),'real-finance');
 const item={id:'axim-bank',name:'Axim Bank',simulated:true,offers:[{id:'standard',annual_rate_bps:1000,max_ltv_percent:60,tenures_months:[6,12]}]};
 assert.equal(parseLenders([item])[0].offers[0].annual_rate_bps,1000);
 for(const v of [[item,item],[{...item,simulated:false}],[{...item,offers:[{...item.offers[0],max_ltv_percent:99}]}],[{...item,offers:[item.offers[0],item.offers[0]]}]])assert.throws(()=>parseLenders(v));
});
test('cash parsing never accepts missing cash as zero or real settlement claims',()=>{
 assert.equal(parseCash({investor_id:'i',balance_minor:'0',currency:'INR',simulated:true},'i').balance_minor,'0');
 for(const v of [{investor_id:'i',currency:'INR',simulated:true},{investor_id:'x',balance_minor:'100',currency:'INR',simulated:true},{investor_id:'i',balance_minor:'-1',currency:'INR',simulated:true}])assert.throws(()=>parseCash(v,'i'));
 assert.equal(parseEntry(entry).kind,'DEMO_FUNDS');assert.throws(()=>parseEntry({...entry,simulated:false}));assert.throws(()=>parseEntry({...entry,status:'COMMITTED_VALID'}));
});
test('uncertain cash outcomes keep original key across navigation and block changed requests',async()=>{
 const store=storage();const flow=createCashFlow(()=>store,()=> 'original');let calls=0;
 await assert.rejects(flow.run('fund','100',async()=>{calls++;throw new RequestError(0,'REQUEST_TIMEOUT','unknown',undefined,undefined,true);}));
 const recovered=createCashFlow(()=>store,()=> 'new-key');
 await assert.rejects(recovered.run('withdraw','100',async()=>{calls++;return entry;}));assert.equal(calls,1);
 await recovered.run('fund','100',async key=>{assert.equal(key,'original');calls++;return entry;});assert.equal(calls,2);assert.equal(recovered.snapshot(),null);
});
test('rapid cash clicks send once; confirmed insufficient funds permit explicit top-up',async()=>{
 const store=storage(),flow=createCashFlow(()=>store,()=> 'key');let finish;
 const pending=flow.run('fund','100',()=>new Promise(resolve=>finish=resolve));
 await assert.rejects(flow.run('fund','100',async()=>entry));finish(entry);await pending;
 await assert.rejects(flow.run('withdraw','200',async()=>{throw new RequestError(409,'INSUFFICIENT_DEMO_FUNDS','Add funds');}));
 assert.equal(flow.snapshot(),null);await flow.run('fund','100',async()=>entry);
});
test('corrupt recovery storage fails before any cash request',async()=>{
 const store=storage();store.setItem('tokansh-demo-cash-attempt-v1','broken');let calls=0;
 await assert.rejects(createCashFlow(()=>store,()=> 'k').run('fund','100',async()=>{calls++;return entry;}));assert.equal(calls,0);
});

test('mismatched wallet response retains recovery key and cannot claim success',async()=>{
 const store=storage(),flow=createCashFlow(()=>store,()=> 'original');
 await assert.rejects(flow.run('withdraw','100',async()=>entry));
 assert.equal(flow.snapshot().key,'original');
 await assert.rejects(flow.run('withdraw','100',async()=>({...entry,kind:'WITHDRAWAL',amount_minor:'99'})));
 assert.equal(flow.snapshot().key,'original');
});
