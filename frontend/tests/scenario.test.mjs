import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';
import {scenarioProperty,scenarioHoldings,scenarioEvents,scenarioEntitlement,inr,phases,ledgerUnavailable} from '../src/demo/scenario.ts';
import {propertyImageFor} from '../src/demo/propertyImages.ts';

test('onboarding starts without registered, committed or issued assets',()=>{
 const p=scenarioProperty('ONBOARDING'),h=scenarioHoldings('ONBOARDING');
 assert.equal(p.issued,0);assert.equal(p.approval,'DRAFT');assert.equal(h.owned,0);assert.equal(h.available,0);
});
test('approved property preview has no issued units until issuance phase',()=>{
 assert.equal(scenarioProperty('APPROVED').issued,0);
 assert.equal(scenarioProperty('ISSUED').issued,100000);
});
test('baseline investor purchase is exactly 500 ANSH, ₹50 lakh',()=>{
 const h=scenarioHoldings('PURCHASED');assert.equal(h.owned,500);assert.equal(h.pledged,0);assert.equal(h.available,500);assert.equal(h.acquisitionValue,'5000000');
 assert.equal(inr(h.acquisitionValue),'₹50,00,000');
});
test('baseline pledge is exactly 200 units with 300 available',()=>{
 const h=scenarioHoldings('PLEDGED');assert.equal(h.owned,500);assert.equal(h.pledged,200);assert.equal(h.available,300);
 assert.ok(350>h.available);
});
test('full release restores 500 transferable units',()=>{
 const h=scenarioHoldings('RELEASED');assert.equal(h.owned,500);assert.equal(h.pledged,0);assert.equal(h.available,500);
});
test('record-date example entitlement is 5000 rupees (illustrative only)',()=>{
 const p=scenarioEntitlement('PLEDGED');assert.equal(p.eligibleUnits,500);assert.equal(p.entitlement,'5000');assert.equal(p.verified,false);
});
test('preview states never fabricate committed DRUNIX evidence',()=>{
 for(const p of phases){for(const e of scenarioEvents(p.id)){
  assert.equal(e.appStatus,'PREVIEW_ONLY');assert.equal(e.ledger.verified,false);assert.equal(e.ledger.transactionId,null);
 }}
 assert.equal(ledgerUnavailable.state,'NOT_CONNECTED');
});

test('showcase photographs resolve by stable friendly symbol with a safe fallback',()=>{
 assert.match(propertyImageFor({symbol:'ANSH-OAK',name:'Silver Oak Residential Plot'}),/silver-oak\.webp$/);
 assert.match(propertyImageFor({symbol:'ANSH-GREEN',name:'Green Acres Farmland'}),/green-acres\.webp$/);
 assert.equal(propertyImageFor({symbol:'ANSH-UNKNOWN',name:'Uncatalogued Property'}),'/images/properties/property-fallback.svg');
 assert.equal(existsSync('public/images/properties/silver-oak.webp'),true);
 assert.equal(existsSync('public/images/properties/property-fallback.svg'),true);
});

test('sidebar collapse control exposes the approved direction and accessible labels',()=>{
 const source=readFileSync(new URL('../src/components/Shell.tsx',import.meta.url),'utf8');
 assert.match(source,/collapsed\?<ChevronRight/);
 assert.match(source,/:<ChevronLeft/);
 assert.match(source,/aria-label=\{collapsed\?'Expand sidebar':'Collapse sidebar'\}/);
});
