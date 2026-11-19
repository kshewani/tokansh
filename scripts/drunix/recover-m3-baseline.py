"""New M3 observation and separate local acceptance; never historical evidence."""
import argparse
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('upgrade_recovery', HERE/'upgrade-workflow.py')
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
KIND = 'NEWLY_OBSERVED_M3_BASELINE'
ACK = 'I independently reviewed and accept this newly observed M3 baseline; it does not replace missing historical proof.'
PROPERTY = 'f6169750-4676-4e99-887f-2bc5471bd518'
OPERATION = 'edaeabd1-78e9-4e9d-a808-92affc2a81af'
TX = '205f60daf6790d1d2a9cc2077026691e6bdef754810c1451c6791f0e892b984f'


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_capture(value):
    u.fields(value, ['schema_version','kind','capture_id','started_at','completed_at','source_revision',
                     'network_root','snapshot','evidence_directory','evidence_sha256'])
    u.require(type(value['schema_version']) is int and value['schema_version'] == 1 and value['kind'] == KIND)
    u.release_id(value['capture_id'])
    dates = [datetime.fromisoformat(value[k]) for k in ('started_at','completed_at')]
    u.require(all(d.tzinfo is not None for d in dates) and dates[0] <= dates[1], 'Invalid observation timestamps')
    u.require(isinstance(value['source_revision'],str) and re.fullmatch('[0-9a-f]{40}',value['source_revision']))
    network = u.external(value['network_root'])
    evidence = u.external(value['evidence_directory'], network); u.private(evidence,True)
    snapshot = u.snapshot(value['snapshot'],value['capture_id'])
    u.require(snapshot['property_id'] == PROPERTY and snapshot['operation_id'] == OPERATION)
    for org in snapshot['organizations'].values():
        u.require(org['property']['approved_supply'] == 100 and org['property']['registration_transaction_id'] == TX,
                  'Unexpected registered property or committed receipt')
    hashes = value['evidence_sha256']
    u.require(isinstance(hashes,dict) and bool(hashes),'Missing observation evidence')
    u.require(set(hashes) == {p.name for p in evidence.iterdir()},'Evidence inventory mismatch')
    for name, digest in hashes.items():
        u.require(isinstance(name,str) and re.fullmatch(r'[0-9]{3,}\.(stdout|stderr)',name),'Invalid evidence filename')
        path = evidence/name; u.private(path)
        u.require(u.digest(path) == u.sha(digest),'Observation evidence hash mismatch')
    return snapshot


def capture(runner, capture_id, revision):
    """Only runner.capture performs peer reads; there is no mutation dispatch."""
    destination = runner.release/'candidate.json'
    u.require(not destination.exists(),'Never overwrite a candidate')
    started = now()
    snapshot = runner.capture(capture_id,PROPERTY,OPERATION)
    hashes = {p.name:u.digest(p) for p in runner.evidence.iterdir()}
    value = dict(schema_version=1,kind=KIND,capture_id=capture_id,started_at=started,completed_at=now(),
                 source_revision=revision,network_root=str(runner.network),snapshot=snapshot,
                 evidence_directory=str(runner.evidence),evidence_sha256=hashes)
    validate_capture(value)
    u.save(destination,value)
    return destination


def candidate(path, reviewed_hash):
    path = u.external(str(path)); u.private(path); u.private(path.parent,True)
    u.require(u.digest(path) == u.sha(reviewed_hash),'Reviewed candidate hash mismatch')
    value = u.checks.load(path)
    snapshot = validate_capture(value)
    u.require(not path.is_relative_to(Path(value['network_root'])))
    u.require(Path(value['evidence_directory']).parent == path.parent,'Evidence belongs to another capture directory')
    return value,snapshot


def accept(path, reviewed_hash, reviewer, acknowledgement):
    u.require(acknowledgement == ACK,'Separate explicit acceptance required')
    u.require(isinstance(reviewer,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._@-]{2,119}',reviewer),'Identify the independent reviewer')
    path = Path(path)
    candidate(path,reviewed_hash)
    destination = path.parent/'accepted-m3.json'
    u.save(destination,dict(schema_version=1,kind=KIND,candidate_path=str(path.resolve()),
                           candidate_sha256=reviewed_hash,accepted_at=now(),reviewer=reviewer,acknowledgement=ACK))
    return destination


def validate_accepted(path, reviewed_hash):
    """Offline gate used by preflight. No network calls and no implicit acceptance."""
    try:
        path = u.external(str(path)); u.private(path); u.private(path.parent,True)
        u.require(u.digest(path) == u.sha(reviewed_hash),'Accepted baseline hash mismatch')
        value = u.checks.load(path)
        u.fields(value,['schema_version','kind','candidate_path','candidate_sha256','accepted_at','reviewer','acknowledgement'])
        u.require(type(value['schema_version']) is int and value['schema_version'] == 1 and value['kind'] == KIND)
        u.require(value['acknowledgement'] == ACK and isinstance(value['reviewer'],str)
                  and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 ._@-]{2,119}',value['reviewer']))
        observed,snapshot = candidate(value['candidate_path'],value['candidate_sha256'])
        accepted = datetime.fromisoformat(value['accepted_at'])
        u.require(accepted.tzinfo is not None and accepted >= datetime.fromisoformat(observed['completed_at']))
        u.require(Path(value['candidate_path']).resolve().parent == path.parent,'Acceptance belongs to another capture')
        return snapshot
    except (u.Stop,OSError,ValueError,TypeError,KeyError,AttributeError):
        raise SystemExit('Validation failed: unaccepted, changed or malformed recovered baseline') from None


def main(argv=None):
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    sub = p.add_subparsers(dest='phase',required=True)
    c = sub.add_parser('capture',allow_abbrev=False)
    c.add_argument('--authorize-read-only-capture',action='store_true',required=True)
    for name in ('network-root','directory','capture-id'):c.add_argument('--'+name,required=True)
    a = sub.add_parser('accept',allow_abbrev=False)
    a.add_argument('--authorize-acceptance',action='store_true',required=True)
    for name in ('candidate','candidate-sha256','reviewer','acknowledgement'):a.add_argument('--'+name,required=True)
    args = p.parse_args(argv)
    if args.phase == 'capture':
        network = u.external(args.network_root)
        directory = u.external(args.directory,network); u.private(directory,True)
        u.require(not any(directory.iterdir()),'Select a new empty private capture directory')
        u.release_id(args.capture_id)
        runner = u.Runner(network,directory)
        revision = runner.run(['git','rev-parse','HEAD'],cwd=u.REPO).strip()
        path = capture(runner,args.capture_id,revision)
        print('CANDIDATE ONLY: independent review and separate acceptance required.')
    else:
        path = accept(args.candidate,args.candidate_sha256,args.reviewer,args.acknowledgement)
        print('NEWLY OBSERVED baseline accepted locally; not historical proof.')
    print('File='+str(path)+'; SHA256='+u.digest(path))


if __name__ == '__main__':
    try:main()
    except (u.Stop,OSError,ValueError,TypeError,KeyError,AttributeError):
        sys.exit('STOP: baseline recovery failed; retain private evidence; no automatic retry or acceptance')
