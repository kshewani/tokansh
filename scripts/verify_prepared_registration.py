#!/usr/bin/env python3
"""Offline verifier. Run with backend/.venv/bin/python; never prints upstream errors."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import tempfile
from urllib.parse import quote


def exact(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate key')
        result[key]=value
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation-id',required=True)
    parser.add_argument('--transaction-id',required=True)
    parser.add_argument('--command',type=Path,required=True)
    parser.add_argument('--database',type=Path,default=Path.home()/'.local/share/tokansh/tokansh.db')
    parser.add_argument('--msp-root',type=Path,default=Path.home()/'projects/drunix/drunix-network/test-network/organizations/peerOrganizations')
    args=parser.parse_args()
    try:
        from dotenv import dotenv_values
        from sqlalchemy.engine import make_url
        profile=Path.home()/'.config/tokansh/local.env'
        parent=profile.parent.stat()
        if parent.st_uid!=os.getuid() or stat.S_IMODE(parent.st_mode)&0o077 or profile.parent.is_symlink():raise ValueError()
        info=profile.stat()
        if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077 or profile.is_symlink():raise ValueError()
        settings=dotenv_values(profile)
        secret=settings.get('TOKANSH_GATEWAY_SECRET')
        if not secret:raise ValueError()
        configured=make_url(settings.get('DATABASE_URL','sqlite:///'+str(Path.home()/'.local/share/tokansh/tokansh.db')))
        if configured.drivername not in ('sqlite','sqlite+pysqlite') or configured.query or configured.host:raise ValueError()
        db=args.database.resolve(strict=True)
        if not Path(configured.database).is_absolute() or not db.samefile(configured.database):raise ValueError()
        frozen=args.command.read_bytes()
        if len(frozen)>4096:raise ValueError()
        # mode=ro prohibits main database mutation; no migration/backup/status call.
        with sqlite3.connect('file:'+quote(str(db))+'?mode=ro',uri=True) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.row_factory=sqlite3.Row
            row=connection.execute('SELECT operation_id,transaction_id,property_id,request_digest,signer,channel,chaincode,state,command_json,artifact_json FROM ledger_operations WHERE operation_id=?',(args.operation_id,)).fetchone()
            if row is None or row['state']!='PREPARED' or row['transaction_id']!=args.transaction_id:raise ValueError()
            request={k:row[k] for k in ('operation_id','transaction_id','property_id','request_digest','signer','channel','chaincode','state')}
            if len(row['artifact_json'])>2<<20:raise ValueError()
            request.update(artifact=json.loads(row['artifact_json'],object_pairs_hook=exact),
                command=json.loads(row['command_json'],object_pairs_hook=exact),frozen=json.loads(frozen,object_pairs_hook=exact),
                secret=secret,trust_path=str(args.msp_root.resolve(strict=True)))
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'GOPROXY':'off','GOSUMDB':'off','GOTOOLCHAIN':'local'}
        with tempfile.TemporaryDirectory(prefix='tokansh-offline-verifier-') as temporary:
            binary=str(Path(temporary)/'verify-prepared')
            subprocess.run(['go','build','-mod=readonly','-o',binary,'./cmd/verify-prepared'],cwd=root/'gateway',env=env,
                check=True,timeout=120,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            result=subprocess.run([binary],input=json.dumps(request).encode(),capture_output=True,timeout=20)
            # Go emits only fixed status codes and validated public UUID/tx identifiers.
            print(result.stdout.decode().strip() or 'FAIL: OFFLINE_VERIFIER_UNAVAILABLE')
            return result.returncode
    except Exception:
        print('FAIL: BLOCKED_OFFLINE_INPUT_OR_TOOLING; no transaction or database mutation attempted')
        return 1


if __name__=='__main__':raise SystemExit(main())
