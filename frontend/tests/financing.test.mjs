import test from 'node:test';
import assert from 'node:assert/strict';
import {financeQuote,moneyINR,rupeesToMinor,parseEligibility,parseLoan} from '../src/api/financing.ts';

test('illustrative loan math uses exact integer paise and fixed-term simple interest',()=>{
 assert.equal(rupeesToMinor('10000.05'),'1000005');
 assert.equal(moneyINR('123456789'),'₹12,34,567.89');
 assert.deepEqual(financeQuote(2,'1000000',60,1000,12),{collateral_value_minor:'2000000',principal_minor:'1200000',interest_minor:'120000',repayment_minor:'1320000'});
 assert.equal(financeQuote(1,'20',50,1000,6).interest_minor,'1');
 assert.equal(financeQuote(9007199254740991,'1000000',60,1000,12).collateral_value_minor,'9007199254740991000000');
 for(const value of ['1e3','-1','0','1.001'])assert.throws(()=>rupeesToMinor(value));
 for(const q of [0,-1,1.5])assert.throws(()=>financeQuote(q,'1000000',60,1000,12));
});
test('financing eligibility is distinct from ledger holdings and flags transferred reservations',()=>{
 const data={property_id:'p',holder_id:'h',owned:2,reserved_simulated:1,eligible_simulated:1,reservation_shortfall:false,on_chain_lock:false,ownership_source:'DRUNIX_EVALUATE',observed_at:'2026-11-20T00:00:00Z'};
 assert.equal(parseEligibility(data,'p','h').owned,2);
 assert.equal(parseEligibility({...data,owned:0,eligible_simulated:0,reservation_shortfall:true},'p','h').reserved_simulated,1);
 for(const value of [{...data,on_chain_lock:true},{...data,eligible_simulated:2},{...data,ownership_source:'LOCAL_DB'}])assert.throws(()=>parseEligibility(value,'p','h'));
});
test('loan responses must be explicitly simulated, exact and never claim a real lock',()=>{
 const data={type:'SIMULATED_FINANCING',id:'70000000-0000-4000-8000-000000000001',borrower_id:'00000000-0000-4000-8000-000000000003',property_id:'f6169750-4676-4e99-887f-2bc5471bd518',asset_class:'ANSH',quantity:1,unit_value_minor:'1000000',ltv_percent:60,annual_rate_bps:1000,term_months:12,...financeQuote(1,'1000000',60,1000,12),state:'APPROVED',reservation_active:true,simulated:true,on_chain_lock:false,outstanding_principal_minor:'0',amount_due_minor:'0',assessment:null,timeline:[{state:'APPROVED',timestamp:'2026-11-20T00:00:00Z',actor_role:'INVESTOR',simulated:true}]};
 assert.equal(parseLoan(data).state,'APPROVED');
 for(const value of [{...data,on_chain_lock:true},{...data,asset_class:'REIT'},{...data,principal_minor:'600001'},{...data,reservation_active:false},{...data,simulated:false}])assert.throws(()=>parseLoan(value));
});
