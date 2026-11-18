import type {SystemComponent,SystemStatus} from './contracts.ts';
import {isRecord,RequestError} from './client.ts';

/** Validate the existing frontend shape; do not guess aliases or infer readiness. */
export function parseSystemStatus(value:unknown):SystemStatus {
 const invalid=()=>new RequestError(200,'MALFORMED_RESPONSE','System Status returned an unsupported response format.');
 if(!isRecord(value)||!Array.isArray(value.components))throw invalid();
 const names=new Set<string>();
 const components:SystemComponent[]=value.components.map((component:unknown)=>{
  if(!isRecord(component)||typeof component.name!=='string'||!component.name.trim()||
   typeof component.status!=='string'||!['CONNECTED','UNAVAILABLE','UNKNOWN','DEGRADED'].includes(component.status)||
   (component.detail!==undefined&&typeof component.detail!=='string'))throw invalid();
  const name=component.name.trim(),key=name.toLowerCase();
  if(names.has(key))throw invalid();
  names.add(key);
  return {name,status:component.status as SystemComponent['status'],detail:component.detail as string|undefined};
 });
 if(value.last_ledger_operation!==undefined&&value.last_ledger_operation!==null&&typeof value.last_ledger_operation!=='string')throw invalid();
 return {components,last_ledger_operation:value.last_ledger_operation as string|null|undefined};
}
export function componentStatus(data:SystemStatus|null,name:string):SystemComponent['status'] {
 return data?.components.find(c=>c.name.toLowerCase()===name.toLowerCase())?.status||'UNKNOWN';
}
