import type {Role} from '../demo/scenario.ts';
export const workspaceRoles=[{role:'INVESTOR' as const,label:'Investor',description:'Invest, manage your portfolio and unlock liquidity.'},{role:'LENDER' as const,label:'Lender',description:'Review applications and manage your institution’s loan book.'}];
export const landing=(role:Role)=>role==='LENDER'?'/lending':'/overview';
export function loanActions(role:Role,state:string){
 if(role==='INVESTOR')return state==='DISBURSED'?['repay']:state==='REPAID'?['release']:[];
 if(role!=='LENDER')return [];
 return state==='APPLIED'?['assess','reject']:state==='ASSESSED'?['approve','reject']:state==='APPROVED'?['disburse']:[];
}
export function readInstitution(store?:Pick<Storage,'getItem'>){try{return store?.getItem('tokansh-lender')||'axim-bank';}catch{return 'axim-bank';}}
