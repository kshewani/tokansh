"""Local operator entry point. Secrets are never accepted as command-line arguments."""
import argparse
import getpass
import json
import httpx
from app.config import Settings
from app.database import Database
from app.registration import RegistrationClient, RegistrationService, exact_object

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','prepare-created','submit','reconcile'])
    parser.add_argument('reference',help='command JSON file for prepare; operation UUID otherwise')
    args=parser.parse_args();settings=Settings();database=Database(settings.database_url)
    if not database.ready(): raise SystemExit('Database migrations are required.')
    capability=getpass.getpass('Operator capability: ')
    try:
        with httpx.Client(timeout=7,trust_env=False,follow_redirects=False) as http:
            client=RegistrationClient(settings.drunix_gateway_url,settings.tokansh_gateway_secret,settings.tokansh_operator_secret,http)
            service=RegistrationService(database,client,settings.tokansh_operator_secret)
            if args.action=='prepare':
                with open(args.reference) as source: command=json.load(source,object_pairs_hook=exact_object)
                result=service.prepare(command,capability)
            else: result=getattr(service,args.action.replace('-','_'))(args.reference,capability)
            print(result)  # State only. SUBMITTED is not registration success.
    finally: database.engine.dispose()

if __name__=='__main__':main()
