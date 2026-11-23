import {RequestError} from './client.ts';
import type {ApiRequest} from './transfers.ts';
import type {AuthRole,AuthSession} from './client.ts';

const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function invalid():never{throw new RequestError(200,'MALFORMED_RESPONSE','The authentication response could not be verified.');}
export function parseAuthSession(value:unknown,token?:string):AuthSession {
 if(!value||typeof value!=='object'||Array.isArray(value))return invalid();
 const v=value as Record<string,unknown>;
 if((token!==undefined&&(!token||typeof token!=='string'))||typeof v.access_token!=='string'&&token===undefined||
  (token===undefined&&v.token_type!=='bearer')||typeof v.username!=='string'||typeof v.display_name!=='string'||
  !['INVESTOR','LENDER'].includes(String(v.role))||typeof v.user_id!=='string'||!uuid.test(v.user_id)||
  !(v.organization_id===null||typeof v.organization_id==='string'))return invalid();
 const access_token=token??String(v.access_token);
 return {access_token,token_type:'bearer',username:v.username,display_name:v.display_name,role:v.role as AuthRole,user_id:v.user_id,organization_id:v.organization_id as string|null};
}
export async function login(request:ApiRequest,username:string,password:string,expectedRole:AuthRole):Promise<AuthSession>{
 const value=await request<unknown>('/api/v1/auth/login',{method:'POST',body:{username,password}});
 const session=parseAuthSession(value);
 if(session.role!==expectedRole)throw new RequestError(401,'INVALID_CREDENTIALS','The selected login type does not match the registered demo identity.');
 return session;
}
export async function currentSession(request:ApiRequest,token:string):Promise<AuthSession>{
 const value=await request<unknown>('/api/v1/auth/me');
 return parseAuthSession(value,token);
}
export async function logout(request:ApiRequest):Promise<void>{
 await request<unknown>('/api/v1/auth/logout',{method:'POST'});
}
