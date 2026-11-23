import {investorDemo,parseBalance} from './transfers.ts';
import type {ApiRequest} from './transfers.ts';
import {incomeSnapshot} from '../demo/investments.ts';
/** Read a new current balance for the review; never POST to a settlement endpoint. */
export async function captureIncomeSnapshot(request:ApiRequest,userId:string,rateMinor:string,id:string,clock=()=>new Date().toISOString()){
 const value=await request<unknown>(`/api/v1/ansh/balances/${investorDemo.property}/${userId}`,{method:'GET'});
 const balance=parseBalance(value,investorDemo.property,userId);
 return incomeSnapshot(id,userId,investorDemo.property,balance.quantity,rateMinor,clock(),'DRUNIX_CURRENT_BALANCE');
}
