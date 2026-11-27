import type {ApiMode} from '../api/client';
import {errorFeedback} from '../api/client';
import type {SystemStatus} from '../api/contracts';
import {componentStatus} from '../api/systemStatus';
import {Button} from './ui/button';
import {Card,Metric,SectionHeading} from './ui/card';
import {Status} from './ui/status';

const components=['FastAPI','Application database','Go gateway','DRUNIX peers','Ordering service','Validation service','DRUNIX state database'];
export type SystemStatusProps={mode:ApiMode;configured:boolean;data:SystemStatus|null;loading:boolean;error:unknown;retry:()=>void};
export function SystemStatusView({mode,configured,data,loading,error,retry}:SystemStatusProps){
 // Hide cached observations after failure and while checking again.
 const observed=mode==='real'&&configured&&!loading&&!error?data:null;
 const getStatus=(name:string)=>mode==='preview'?'UNAVAILABLE':componentStatus(observed,name);
 const lastOperation=observed?.last_ledger_operation;
 return <><SectionHeading title="System Status" description="Operational transparency for the Python application and the DRUNIX network."/>
  <div className="grid gap-4 md:grid-cols-3">
   <Metric label="Python backend" value={mode==='preview'?'Not connected':getStatus('FastAPI')} description="HTTP availability is not ledger readiness"/>
   <Metric label="DRUNIX evidence" value="Unverified" description="Verify individual transaction commitment"/>
   <Metric label={mode==='preview'?'Last successful ledger operation':'Last ledger operation reported by backend'} value={lastOperation?.trim()?lastOperation:'Not available'} description="A reported reference alone is not proof of successful commitment"/>
  </div>
  <Card className="mt-5" title="Infrastructure components" description="No network secrets, certificates or internal topology details exposed">
   {mode==='preview'?<p className="mb-4 text-sm text-slate-500">Service status is not requested for this workspace.</p>:
    !configured?<p role="alert" className="mb-4 text-sm text-red-700">Live API access is configured but the API URL is missing. Set VITE_API_BASE_URL and reload the application.</p>:
    <div className="mb-4 space-y-3">
     {loading&&<p role="status" className="text-sm text-slate-500">Checking API status…</p>}
     {!!error&&<p role="alert" className="text-sm text-red-700">{errorFeedback(error)}</p>}
     <Button variant="secondary" size="sm" onClick={retry} disabled={loading}>{error?'Retry status check':'Refresh status'}</Button>
    </div>}
   <div className="data-table-wrap"><table className="data-table w-full"><thead><tr><th>Component</th><th>Observed status</th><th>Explanation</th></tr></thead><tbody>
    {components.map(name=><tr key={name}><td className="font-semibold">{name}</td><td><Status value={getStatus(name)}/></td><td>{mode==='preview'?'No verified integration status returned.':getStatus(name)==='UNKNOWN'?'No current component status established.':'Reported by Python system API'}</td></tr>)}
    {observed?.components.filter(c=>!components.some(name=>name.toLowerCase()===c.name.toLowerCase())).map(c=><tr key={c.name}><td className="font-semibold">{c.name}</td><td><Status value={c.status}/></td><td>Reported by Python system API</td></tr>)}
   </tbody></table></div>
  </Card>
  <div className="mt-5 rounded-lg border border-blue-200 bg-blue-50 p-4 text-xs leading-6 text-blue-900"><strong>Integration boundary:</strong> The frontend checks <code>GET /api/v1/system/status</code> when an API URL is configured. A healthy FastAPI response does not establish DRUNIX transaction capability or commitment.</div>
 </>;
}
