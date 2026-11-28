import test from 'node:test';
import assert from 'node:assert/strict';
import {inr,integer,multiplyAmount,shortRef,toPaise} from '../src/lib/format.ts';

test('INR display uses Indian grouping',()=>{
 assert.equal(inr('5000000.00'),'₹50,00,000');
 assert.equal(inr('1000000000',true),'₹100.00 Cr');
 assert.equal(inr(null),'—');
});
test('display multiplication is exact (no binary floating point)',()=>{
 assert.equal(multiplyAmount(500,'10000'),'5000000.00');
 assert.equal(multiplyAmount(3,'0.10'),'0.30');
 assert.equal(multiplyAmount(100000,'10000.01'),'1000001000.00');
 assert.equal(multiplyAmount(2,'1.234'),'');
});
test('transaction references are shortened but never invented',()=>{
 assert.equal(shortRef(null),'—');
 assert.equal(shortRef('abc'),'abc');
 assert.equal(integer(100000),'1,00,000');
});

test('amount comparison uses exact paise',()=>{
 assert.equal(toPaise('5000000.00'),500000000n);
 assert.equal(toPaise('0.1'),10n);
 assert.equal(toPaise('-2.05'),-205n);
 assert.equal(toPaise('1.234'),null);
 assert.ok(toPaise('999999.99')<toPaise(multiplyAmount(100,'10000')));
});
