import test from 'node:test';
import assert from 'node:assert/strict';
import {createSubmitGuard,failureMessage} from '../src/lib/guard.ts';

test('a second submission is blocked until the first finishes',()=>{
 const g=createSubmitGuard();
 assert.equal(g.tryEnter(),true);assert.equal(g.tryEnter(),false);assert.equal(g.busy,true);
 g.exit();assert.equal(g.tryEnter(),true);
});
test('a lost response is reported as an unknown outcome, never as a failure to retry',()=>{
 const m=failureMessage('Pledge',0,'BACKEND_UNAVAILABLE','x');
 assert.match(m,/may or may not have been processed/);assert.match(m,/do not resubmit/);
});
test('ambiguous ledger outcomes point to reconciliation',()=>{
 assert.match(failureMessage('Transfer',202,'LEDGER_OUTCOME_UNKNOWN','Outcome unknown.'),/Reconcile/);
 assert.equal(failureMessage('Order',409,'PAYMENT_FAILED','Declined.'),'Order: Declined. (PAYMENT_FAILED)');
});
