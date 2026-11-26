import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequest} from '../src/api/client.ts';
import {deriveSupply,parsePortfolio,propertyTokenId} from '../src/api/properties.ts';
import {parseOffering,parsePurchase,parseWalletBalance,purchaseStorageKey,readPurchaseRecovery,writePurchaseRecovery} from '../src/api/marketplace.ts';

const issuer='00000000-0000-4000-8000-000000000003';
const buyer='00000000-0000-4000-8000-000000000006';
const property='f6169750-4676-4e99-887f-2bc5471bd518';
const offering='70000000-0000-4000-8000-000000000001';
const purchase='80000000-0000-4000-8000-000000000001';
const base={id:offering,property_id:property,issuer_id:issuer,offered_quantity:10,sold_quantity:2,reserved_quantity:3,available_quantity:5,price_minor:'100000',currency:'INR',status:'ACTIVE',created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'};
const result={operation_id:purchase,offering_id:offering,property_id:property,buyer_id:buyer,seller_id:issuer,quantity:2,price_minor:'100000',total_amount_minor:'200000',currency:'INR',state:'SETTLED',transfer_operation_id:purchase,transaction_id:'a'.repeat(64),error_code:null,created_at:'2026-01-01T00:00:00Z',updated_at:'2026-01-01T00:00:00Z'};
const store=()=>{const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};};

test('supply and property identity remain integer and property-specific',()=>{
 assert.equal(deriveSupply('10000000'),10000);
 assert.equal(deriveSupply('10000001'),null);
 assert.equal(propertyTokenId(property),'ANSH-'+property);
 assert.notEqual(propertyTokenId(property),propertyTokenId('f6169750-4676-4e99-887f-2bc5471bd519'));
 assert.equal(propertyTokenId(`  ${property.toUpperCase()}  `),propertyTokenId(property));
 assert.equal(parseOffering(base).property_id,property);
 assert.equal(parsePurchase(result).property_id,property);
});

test('offering, purchase and wallet parsers reject inconsistent observations',()=>{
 assert.equal(parseOffering(base).available_quantity,5);
 assert.equal(parsePurchase(result).state,'SETTLED');
 assert.equal(parseWalletBalance({investor_id:buyer,balance_minor:'500000',reserved_minor:'200000',available_minor:'300000',currency:'INR',simulated:true},buyer).available_minor,'300000');
 assert.equal(parseWalletBalance({investor_id:buyer,balance_minor:'0',reserved_minor:'0',available_minor:'0',currency:'INR',simulated:true},buyer).available_minor,'0');
 assert.throws(()=>parseOffering({...base,available_quantity:6}),{code:'MALFORMED_RESPONSE'});
 assert.throws(()=>parsePurchase({...result,total_amount_minor:'1'}),{code:'MALFORMED_RESPONSE'});
 assert.throws(()=>parseWalletBalance({investor_id:buyer,balance_minor:'100',reserved_minor:'75',available_minor:'30',currency:'INR',simulated:true},buyer),{code:'MALFORMED_RESPONSE'});
});

test('purchase recovery preserves the original idempotency key and operation',()=>{
 const memory=store(),key=purchaseStorageKey(buyer,offering),value={key:'original-key',operationId:purchase,result};
 writePurchaseRecovery(memory,key,value);
 assert.deepEqual(readPurchaseRecovery(memory,key),value);
});

test('purchase request uses bearer transport and stable idempotency key',async()=>{
 const request=createRequest({mode:'real',baseUrl:'https://api.example.test',configured:true},async(_url,options)=>{
  assert.equal(options.headers.Authorization,undefined);
  assert.equal(options.headers['Idempotency-Key'],'original-key');
  assert.deepEqual(JSON.parse(options.body),{offering_id:offering,quantity:2});
  return new Response(JSON.stringify({data:result}),{status:200,headers:{'Content-Type':'application/json'}});
 });
 const value=await request('/api/v1/marketplace/purchases',{method:'POST',body:{offering_id:offering,quantity:2},idempotencyKey:'original-key'});
 assert.equal(value.operation_id,purchase);
});

test('portfolio parser preserves independent property identity and rejects fabricated unavailable balances',()=>{
 const portfolio={investor_id:buyer,currency:'INR',source:'DRUNIX_EVALUATE',items:[
  {property_id:property,ansh_id:propertyTokenId(property),name:'Property A',category:'Office',location:'Bengaluru',issuer_id:issuer,registration_status:'REGISTERED',issuance_status:'ISSUED',approved_valuation_minor:'1000000000',initial_issue_price_minor:'100000',currency:'INR',approved_supply:10000,issued_supply:10000,owned_units:500,pledged_units:0,offering_committed_units:0,transferable_units:500,observation_status:'AVAILABLE',source:'DRUNIX_EVALUATE',observed_at:'2026-11-20T00:00:00Z',error_code:null},
  {property_id:'f6169750-4676-4e99-887f-2bc5471bd519',ansh_id:'ANSH-f6169750-4676-4e99-887f-2bc5471bd519',name:'Property B',category:'Office',location:'Pune',issuer_id:issuer,registration_status:'REGISTERED',issuance_status:'UNAVAILABLE',approved_valuation_minor:'500000000',initial_issue_price_minor:'200000',currency:'INR',approved_supply:5000,issued_supply:null,owned_units:null,pledged_units:0,offering_committed_units:0,transferable_units:null,observation_status:'UNAVAILABLE',source:'DRUNIX_EVALUATE',observed_at:null,error_code:'GATEWAY_UNAVAILABLE'}],
  aggregate:{status:'PARTIAL',observed_property_count:1,total_indicative_value_minor:null,valuation_basis:null}};
 const parsed=parsePortfolio(portfolio,buyer);assert.equal(parsed.items[0].owned_units,500);assert.notEqual(parsed.items[0].ansh_id,parsed.items[1].ansh_id);
 assert.throws(()=>parsePortfolio({...portfolio,items:[{...portfolio.items[1],owned_units:0}]},buyer),{code:'MALFORMED_RESPONSE'});
 assert.throws(()=>parsePortfolio({...portfolio,items:[{...portfolio.items[0],ansh_id:'ANSH-wrong-property'}]},buyer),{code:'MALFORMED_RESPONSE'});
 assert.throws(()=>parsePortfolio({...portfolio,aggregate:{...portfolio.aggregate,status:'COMPLETE',total_indicative_value_minor:'100000'}},buyer),{code:'MALFORMED_RESPONSE'});
});
