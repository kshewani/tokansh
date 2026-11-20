import {investorDemo,parseBalance} from './transfers.ts';
import type {ApiRequest} from './transfers.ts';
import type {Role} from '../demo/scenario.ts';
import {incomeSnapshot} from '../demo/investments.ts';
/** Read a new current balance for the review; never POST to a settlement endpoint. */
export async function captureIncomeSnapshot(request:ApiRequest,role:Role,rateMinor:string,id:string,clock=()=>new Date().toISOString()){
 const value=await request<unknown>(`/api/v1/ansh/balances/${investorDemo.property}/${investorDemo.investor}`,{method:'GET',demoRole:role});
 const balance=parseBalance(value,investorDemo.investor);
 return incomeSnapshot(id,investorDemo.investor,investorDemo.property,balance.quantity,rateMinor,clock(),'DRUNIX_CURRENT_BALANCE');
}
