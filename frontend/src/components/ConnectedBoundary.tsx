import type {ReactNode} from 'react';
import {Link} from 'react-router-dom';
import type {ApiMode} from '../api/client';
import {screenIntegrated} from '../app/integration';
import {Card,EmptyState,SectionHeading} from './ui/card';
import {Button} from './ui/button';

export function ConnectedBoundary({mode,path,title,children}:{mode:ApiMode;path:string;title:string;children:ReactNode}){
 if(screenIntegrated(mode,path))return <>{children}</>;
 return <><SectionHeading title={title} description="Authoritative business data unavailable"/>
  <Card><EmptyState title="This screen is not integrated yet" description="Authoritative backend data is not available on this screen. Balances, financial actions and transaction history remain unavailable until this workflow is connected."/>
   <Button asChild variant="secondary" className="mt-4"><Link to="/system">View System Status</Link></Button>
  </Card></>;
}
