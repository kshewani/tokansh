import test from 'node:test';
import assert from 'node:assert/strict';
import {inr,integer,multiplyAmount,shortRef} from '../src/lib/format.ts';

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
