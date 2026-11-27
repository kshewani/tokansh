"""Guarded local-only TokANSH upgrade: one authorized phase, strict inspection, no retries.

Approval absence is never inferred. Native one-shot desired-state approval needs
an independently bound replacement/repair acknowledgement. No business invocations.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

checks = module('deployment-checks')
inspect = module('lifecycle-inspect')
POLICY = "AND('Org1MSP.peer','Org2MSP.peer')"
LIFETIME_SUPPLY = 'LIFETIME_CUMULATIVE_ISSUANCE_CEILING'
ONE_TIME_SUPPLY = 'ONE_TIME_FULL_SUPPLY_ISSUANCE'
BASE_FUNCTIONS = ['GetContractInfo', 'GetRegisteredProperty', 'GetOperation', 'RegisterApprovedProperty']
ISSUANCE_FUNCTIONS = BASE_FUNCTIONS + ['IssueANSH', 'GetIssuanceState', 'GetBalance', 'GetIssuanceOperation']
TRANSFER_FUNCTIONS = ISSUANCE_FUNCTIONS + ['TransferANSH']
FUNCTIONS = list(BASE_FUNCTIONS)
M4_FUNCTIONS = list(ISSUANCE_FUNCTIONS)
PHASES = ['package', 'preflight', 'install-org1', 'install-org2', 'approve-org1',
          'approve-org2', 'verify-approval-org1', 'verify-approval-org2', 'readiness', 'commit', 'verify']
PARAMS = dict(channel='mychannel', chaincode='tokansh', current_version='1.0',
              current_sequence=1, version='1.1', sequence=2, policy=POLICY, init_required=False)
M42 = False
SOURCE_SUPPLY_INTERPRETATION = LIFETIME_SUPPLY
TARGET_SUPPLY_INTERPRETATION = LIFETIME_SUPPLY
PINNED_SUPERVISED_ISSUANCE = False
APPROVAL_FIELD = 'approval_v1'

UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')
APPROVAL_ACK = ('I authorize one attempt to establish the reviewed TokANSH version 1.1 sequence-2 approval '
                'for this organization, including replacement or repair of an existing uncommitted approval.')
MAINTENANCE_ACK = ('I confirm an operator-controlled maintenance window on mychannel with no competing '
                   'lifecycle operators or known in-flight lifecycle operations.')

def configure_transition(current_version, current_sequence, version, sequence,
                         source_functions=None, target_functions=None,
                         source_supply=LIFETIME_SUPPLY, target_supply=ONE_TIME_SUPPLY,
                         channel='mychannel', chaincode='tokansh', policy=POLICY,
                         pin_issuance=False):
    """Select one explicit, reviewed in-place lifecycle transition."""
    global M42, APPROVAL_FIELD, FUNCTIONS, M4_FUNCTIONS, APPROVAL_ACK, MAINTENANCE_ACK
    global SOURCE_SUPPLY_INTERPRETATION, TARGET_SUPPLY_INTERPRETATION, PINNED_SUPERVISED_ISSUANCE
    require(not M42, 'An upgrade profile is already selected')
    require(re.fullmatch(r'[0-9]+\.[0-9]+', str(current_version)) is not None
            and re.fullmatch(r'[0-9]+\.[0-9]+', str(version)) is not None)
    require(type(current_sequence) is int and type(sequence) is int
            and current_sequence >= 1 and sequence == current_sequence + 1,
            'Target sequence must be exactly current sequence plus one')
    source_functions = list(source_functions or TRANSFER_FUNCTIONS)
    target_functions = list(target_functions or source_functions)
    require(source_functions and target_functions
            and source_functions[:len(BASE_FUNCTIONS)] == BASE_FUNCTIONS
            and target_functions[:len(BASE_FUNCTIONS)] == BASE_FUNCTIONS)
    require(source_supply in (LIFETIME_SUPPLY, ONE_TIME_SUPPLY)
            and target_supply in (LIFETIME_SUPPLY, ONE_TIME_SUPPLY))
    require(isinstance(channel, str) and channel and chaincode == 'tokansh'
            and policy == POLICY)
    M42 = True
    APPROVAL_FIELD = 'approval_previous'
    FUNCTIONS = source_functions
    M4_FUNCTIONS = target_functions
    SOURCE_SUPPLY_INTERPRETATION = source_supply
    TARGET_SUPPLY_INTERPRETATION = target_supply
    PINNED_SUPERVISED_ISSUANCE = pin_issuance
    PARAMS.update(channel=channel, chaincode=chaincode, policy=policy,
                  current_version=str(current_version), current_sequence=current_sequence,
                  version=str(version), sequence=sequence)
    APPROVAL_ACK = (f'I authorize one attempt to establish the reviewed TokANSH version {version} '
                    f'sequence-{sequence} approval for this organization, including replacement or repair '
                    'of an existing uncommitted approval.')
    MAINTENANCE_ACK = (f'I confirm an operator-controlled maintenance window on {channel} with no competing '
                       'lifecycle operators or known in-flight lifecycle operations.')


def configure_m42():
    """Backward-compatible M4.2 transition: 1.1/2 -> 1.2/3."""
    configure_transition('1.1', 2, '1.2', 3,
                         source_functions=ISSUANCE_FUNCTIONS,
                         target_functions=TRANSFER_FUNCTIONS,
                         source_supply=LIFETIME_SUPPLY,
                         target_supply=ONE_TIME_SUPPLY,
                         pin_issuance=True)


def configure_next_transition(current_version, current_sequence, version, sequence,
                              channel='mychannel', chaincode='tokansh', policy=POLICY):
    """Configure a later transition from the transfer-capable contract."""
    configure_transition(current_version, current_sequence, version, sequence,
                         source_functions=TRANSFER_FUNCTIONS,
                         target_functions=TRANSFER_FUNCTIONS,
                         source_supply=ONE_TIME_SUPPLY,
                         target_supply=ONE_TIME_SUPPLY,
                         channel=channel, chaincode=chaincode, policy=policy)

def package_label():
    return PARAMS['chaincode'] + '_' + PARAMS['version']

ISSUANCE_ID = '97a0703a-1d08-482d-ae1c-90f24a9c5e48'
ISSUANCE_TX = 'acae76b82c30a53372127bd73f15e511fb9795fbd142a970d1ff27e0c7f4a59a'
ISSUER_ID = '00000000-0000-4000-8000-000000000002'
ISSUANCE_FIELDS = ('issuance', 'issuer_balance', 'issuance_operation')

def issuance_records(row):
    """Validate issuance observations and optionally pin the reviewed demo record."""
    prop = row['property']; receipt = row['issuance_operation']
    if not PINNED_SUPERVISED_ISSUANCE:
        state = row['issuance']; balance = row['issuer_balance']
        fields(state, ['schema_version', 'property_id', 'issuer_id', 'approved_supply',
                       'cumulative_issued_supply', 'remaining_issuance_capacity'])
        fields(balance, ['schema_version', 'property_id', 'holder_id', 'quantity'])
        fields(receipt, ['schema_version', 'operation_id', 'authorizing_msp', 'authorizing_principal',
                         'function', 'request_digest', 'property_id', 'issuer_id', 'quantity',
                         'original_transaction_id', 'result'])
        identifier(prop['property_id']); identifier(prop['issuer_id'])
        require(state['schema_version'] == 1 and state['property_id'] == prop['property_id']
                and state['issuer_id'] == prop['issuer_id']
                and type(state['approved_supply']) is int and state['approved_supply'] >= 1
                and type(state['cumulative_issued_supply']) is int
                and 0 <= state['cumulative_issued_supply'] <= state['approved_supply']
                and type(state['remaining_issuance_capacity']) is int
                and state['remaining_issuance_capacity'] == state['approved_supply'] - state['cumulative_issued_supply'],
                'Invalid issuance state')
        require(balance['schema_version'] == 1 and balance['property_id'] == prop['property_id']
                and balance['holder_id'] == prop['issuer_id'] and type(balance['quantity']) is int
                and 0 <= balance['quantity'] <= state['cumulative_issued_supply'], 'Invalid issuer balance')
        identifier(receipt['operation_id']); sha(receipt['request_digest'])
        require(receipt['schema_version'] == 1 and receipt['authorizing_msp'] == 'Org1MSP'
                and isinstance(receipt['authorizing_principal'], str) and receipt['authorizing_principal']
                and receipt['function'] == 'IssueANSH' and receipt['property_id'] == prop['property_id']
                and receipt['issuer_id'] == prop['issuer_id'] and type(receipt['quantity']) is int
                and receipt['quantity'] >= 1 and isinstance(receipt['original_transaction_id'], str)
                and receipt['original_transaction_id'], 'Invalid issuance operation')
        return
    pid = 'f6169750-4676-4e99-887f-2bc5471bd518'
    require(prop['property_id'] == pid and prop['issuer_id'] == ISSUER_ID
            and prop['approved_supply'] == 100
            and prop['registration_operation_id'] == 'edaeabd1-78e9-4e9d-a808-92affc2a81af'
            and prop['registration_transaction_id'] == '205f60daf6790d1d2a9cc2077026691e6bdef754810c1451c6791f0e892b984f',
            'Unexpected protected registration')
    state = dict(schema_version=1,property_id=pid,issuer_id=ISSUER_ID,approved_supply=100,
                 cumulative_issued_supply=10,remaining_issuance_capacity=90)
    balance = dict(schema_version=1,property_id=pid,holder_id=ISSUER_ID,quantity=10)
    for name, expected in (('issuance',state),('issuer_balance',balance)):
        fields(row[name],expected)
        require(all(type(row[name][k]) is type(v) and row[name][k] == v for k,v in expected.items()),
                'Unexpected preserved '+name)
    expected = dict(schema_version=1,operation_id=ISSUANCE_ID,authorizing_msp='Org1MSP',
        authorizing_principal=prop['registered_by_principal'],function='IssueANSH',
        request_digest=receipt.get('request_digest'),property_id=pid,issuer_id=ISSUER_ID,
        quantity=10,original_transaction_id=ISSUANCE_TX,
        result=dict(property_id=pid,issuer_id=ISSUER_ID,operation_id=ISSUANCE_ID,transaction_id=ISSUANCE_TX,
                    quantity=10,cumulative_issued_supply=10,remaining_issuance_capacity=90,issuer_balance=10))
    fields(receipt,expected); sha(receipt['request_digest'])
    require(json.dumps(receipt,sort_keys=True,allow_nan=False) == json.dumps(expected,sort_keys=True,allow_nan=False), 'Unexpected preserved issuance receipt')

class Stop(Exception):
    pass

class CommandTimeout(Stop):
    pass

class CLIRejected(Stop):
    """Private diagnostics; str(error) is always sanitized, including at top level."""
    def __init__(self, returncode, stdout, stderr):
        super().__init__('UNKNOWN: CLI failed; absence/effect not established, no retry')
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

def require(ok, message='Malformed or conflicting upgrade input'):
    if not ok:
        raise Stop(message)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fields(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected))

def sha(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None)
    return value

def identifier(value):
    require(isinstance(value, str) and UUID.fullmatch(value) is not None)
    return value

def release_id(value):
    require(isinstance(value, str) and re.fullmatch('[A-Za-z0-9_-]{8,80}', value) is not None)
    return value

def desired_state_authorization(phase, manifest, binding, flags):
    require(phase in ('approve-org1', 'approve-org2'), 'Desired-state authorization is organization-specific to approval')
    fields(flags, ['path', 'sha256', 'acknowledgement', 'maintenance_acknowledgement'])
    require(flags['acknowledgement'] == APPROVAL_ACK, 'Exact replacement/repair acknowledgement required')
    require(flags['maintenance_acknowledgement'] == MAINTENANCE_ACK, 'Explicit exclusive maintenance-window acknowledgement required')
    path = external(flags['path'], Path(manifest['network_root']))
    require(path.parent == Path(manifest['release_directory']), 'Approval authorization must belong to this release')
    private(path)
    require(path.stat().st_size <= 4096 and digest(path) == sha(flags['sha256']), 'Reviewed approval authorization hash mismatch')
    value = checks.load(path)
    expected = dict(schema_version=2, **approval_scope(manifest, binding, phase[-1]),
                    acknowledgement=APPROVAL_ACK, maintenance_acknowledgement=MAINTENANCE_ACK)
    fields(value, expected)
    require(all(type(value[k]) is type(v) and value[k] == v for k,v in expected.items()),
            'Approval authorization does not match this organization/reviewed release')
    return dict(binding=value, authorization_sha256=flags['sha256'])

def approval_scope(manifest, binding, org):
    return dict(organization='Org'+org+'MSP', channel=manifest['channel'], chaincode=manifest['chaincode'],
        version=manifest['version'], sequence=manifest['sequence'], package_id=manifest['package_id'],
        context_sha256=sha(binding), deployment_id=manifest['deployment_id'])

def verification_files(release, org):
    paths = sorted(release.glob('approval-verification-org'+org+'-*.json'))
    require(all(re.fullmatch('approval-verification-org'+org+r'-[0-9]{8}\.json', p.name) for p in paths),
            'Malformed approval-verification filename; manual review required')
    return paths

def save_approval_verification(runner, manifest, binding, org, observation, current_channel, preserved, evidence):
    paths = verification_files(runner.release,org)
    number = int(paths[-1].stem.rsplit('-',1)[1])+1 if paths else 1
    require(number <= 99999999)
    path = runner.release/f'approval-verification-org{org}-{number:08}.json'
    save(path,dict(schema_version=1,scope=approval_scope(manifest,binding,org),observation=observation,
                  channel=current_channel,preservation_verified=preserved,original_attempt=evidence))

def require_verification(runner, manifest, binding, org, observed, current_channel):
    paths = verification_files(runner.release, org)
    require(bool(paths), 'Separate organization approval verification is required')
    path = paths[-1]; private(path)
    value = checks.load(path)
    fields(value, ['schema_version','scope','observation','channel','preservation_verified','original_attempt'])
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['scope'] == approval_scope(manifest, binding, org)
            and type(value['scope']['sequence']) is int and value['preservation_verified'] is True,
            'Approval verification is not bound to this reviewed context')
    observation = value['observation']
    require(isinstance(observation, dict) and observation.get('state') == 'MATCH',
            'Latest approval verification is not MATCH; manual review required')
    fields(observation,['state','observed'])
    approval(observation['observed'], PARAMS['version'], PARAMS['sequence'], manifest['package_id'])
    require(observation['observed'] == observed, 'Approval changed after independent verification')
    previous, current = channel(value['channel']), channel(current_channel)
    require(current['height'] >= previous['height'], 'Verification is ahead of current ledger')
    if current['height'] == previous['height']: require(current == previous, 'Verification channel hashes disagree')
    evidence = value['original_attempt']
    require(isinstance(evidence,dict) and evidence.get('transaction_validation') == 'UNKNOWN'
            and type(evidence.get('present')) is bool and type(evidence.get('native_acknowledgement_present')) is bool
            and evidence == original_attempt_evidence(runner,manifest,binding,org),
            'Unsupported transaction-validation evidence; never infer COMMITTED_VALID')
    return value

def original_attempt_evidence(runner, manifest, binding, org):
    marker = runner.release/('attempt-approve-org'+org+'.json')
    ack = runner.release/('acknowledged-approve-org'+org+'.json')
    result = dict(present=marker.exists(), native_acknowledgement_present=ack.exists(),
                  transaction_validation='UNKNOWN',
                  limitation='Approval state and CLI acknowledgement do not identify/validate the original transaction.')
    if marker.exists():
        private(marker); intent=checks.load(marker)
        require(intent.get('state') == 'UNKNOWN' and intent.get('phase') == 'approve-org'+org
                and intent.get('context_sha256') == binding, 'Attempt marker belongs to another operation/context')
        authorization = intent.get('desired_state_authorization')
        fields(authorization, ['binding','authorization_sha256'])
        expected = dict(schema_version=2, **approval_scope(manifest,binding,org),
                        acknowledgement=APPROVAL_ACK,maintenance_acknowledgement=MAINTENANCE_ACK)
        require(isinstance(authorization['binding'],dict) and set(authorization['binding']) == set(expected)
                and all(type(authorization['binding'][k]) is type(v) and authorization['binding'][k] == v for k,v in expected.items()),
                'Attempt marker authorization mismatch')
        sha(authorization['authorization_sha256'])
        result['intent_sha256'] = digest(marker)
        if 'command_evidence_directory' in intent:
            directory = external(intent['command_evidence_directory'],runner.network)
            require(directory.parent == runner.release, 'Unexpected command evidence location')
            private(directory,True)
            # Retain references for manual examination, never parse log text as
            # proof of the original transaction's identity or validation result.
            result['diagnostics_directory'] = str(directory)
    else:
        require(not ack.exists(), 'Orphaned acknowledgement without durable intent')
    if ack.exists():
        private(ack); value=checks.load(ack)
        fields(value,['state','context_sha256'])
        require(value['state'] == 'ACKNOWLEDGED_NOT_VERIFIED' and value['context_sha256'] == binding,
                'Acknowledgement context mismatch')
        result['native_acknowledgement_sha256'] = digest(ack)
    return result

def verify_approval(runner, manifest, baseline, binding, org, actual):
    evidence = original_attempt_evidence(runner,manifest,binding,org)
    try:
        observation = runner.observe_desired_approval(org,manifest['package_id'])
    except (Stop,SystemExit,ValueError,TypeError,KeyError,AttributeError):
        observation = dict(state='UNKNOWN',reason='Approval inspection failed; inspect private diagnostics')
    # Separate command; stable snapshot must cover the independent observation.
    after = runner.capture(manifest['deployment_id'],baseline['property_id'],baseline['operation_id'])
    preserve(baseline,after,False)
    require(after['organizations']['1']['channel'] == actual['organizations']['1']['channel'],
            'Channel changed during independent approval verification')
    save_approval_verification(runner,manifest,binding,org,observation,
                               after['organizations'][org]['channel'],True,evidence)
    require(observation['state'] == 'MATCH', observation['state']+': approval not verified; no progression authorized')
    print('MATCH: independent desired-state/preservation verification recorded. Original transaction validation remains UNKNOWN. STOP.')

def external(value, network=None):
    require(isinstance(value, str) and value.startswith('/') and not any(c in value for c in '\0\r\n'))
    path = Path(value).resolve()
    require(not path.is_relative_to(REPO) and (network is None or not path.is_relative_to(network)),
            'Release files must be outside both repositories')
    return path

def private(path, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
            'Release files/directories must be operator-owned and owner-only')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))

def save(path, value):
    # Exclusive creation: never overwrite baselines, artifacts or mutation receipts.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump(value, out, sort_keys=True, separators=(',', ':'), allow_nan=False)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    syncdir(path.parent)

def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def definitions(value):
    fields(value, ['chaincode_definitions'])
    require(isinstance(value['chaincode_definitions'], list))
    result = {}
    for row in value['chaincode_definitions']:
        inspect.definition(row, True)  # strict shape/types, not its v1-only match result
        require(row['name'] not in result, 'Duplicate chaincode definition')
        result[row['name']] = {**row, 'init_required': row.get('init_required', False)}
    require('basic' in result and PARAMS['chaincode'] in result, 'Required committed definition missing')
    return result

def expected_definition(value, version, sequence):
    inspect.definition(value, True)
    expected = dict(name=PARAMS['chaincode'], version=version, sequence=sequence,
                    endorsement_plugin='escc', validation_plugin='vscc',
                    validation_parameter=inspect.POLICY, collections={}, init_required=False)
    require({**value, 'init_required': value.get('init_required', False)} == expected,
            'Unexpected TokANSH lifecycle definition or endorsement policy')

def approval(value, version, sequence, package_id=None):
    inspect.definition(value, False)
    source = value.get('source')
    fields(source, ['Type']); fields(source['Type'], ['LocalPackage'])
    fields(source['Type']['LocalPackage'], ['package_id'])
    package = source['Type']['LocalPackage']['package_id']
    inspect.package(package)
    row = {k: v for k, v in value.items() if k != 'source'}
    expected_definition(dict(row, name=PARAMS['chaincode']), version, sequence)
    require(package_id is None or package == package_id, 'Conflicting approval package')
    return {**value, 'init_required': value.get('init_required', False)}

def readiness(value):
    require(isinstance(value, dict) and {'approvals'} <= value.keys() <= {'approvals', 'mismatches'})
    fields(value['approvals'], ['Org1MSP', 'Org2MSP'])
    if 'mismatches' in value:
        require(isinstance(value['mismatches'], dict) and value['mismatches'] == {})
    require(all(v is True for v in value['approvals'].values()) and not value.get('mismatches'),
            'Both exact organization approvals are required')

def assets(value):
    require(isinstance(value, list) and len(value) == 6, 'Expected six basic assets')
    seen = set()
    for row in value:
        fields(row, ['ID', 'Color', 'Size', 'Owner', 'AppraisedValue'])
        require(all(isinstance(row[k], str) and row[k] for k in ('ID', 'Color', 'Owner')))
        require(all(type(row[k]) is int for k in ('Size', 'AppraisedValue')))
        require(row['ID'] not in seen); seen.add(row['ID'])
    return sorted(value, key=lambda a: a['ID'])

def info(value, upgraded):
    fields(value, ['contract', 'schema_version', 'functions', 'supply_interpretation'])
    require(value['contract'] == PARAMS['chaincode'] and type(value['schema_version']) is int and value['schema_version'] == 1
            and value['functions'] == (M4_FUNCTIONS if upgraded else FUNCTIONS)
            and value['supply_interpretation'] == (TARGET_SUPPLY_INTERPRETATION if upgraded else SOURCE_SUPPLY_INTERPRETATION),
            'Unexpected contract metadata')

def records(prop, op, property_id, operation_id):
    fields(prop, ['schema_version', 'property_id', 'issuer_id', 'approval_reference', 'approval_digest',
        'approved_supply', 'issue_price_minor', 'currency', 'registered_by_msp', 'registered_by_principal',
        'registration_operation_id', 'registration_transaction_id', 'proposal_timestamp'])
    fields(op, ['schema_version', 'operation_id', 'authorizing_msp', 'authorizing_principal', 'function',
        'request_digest', 'property_id', 'original_transaction_id', 'result'])
    fields(op['result'], ['property_id', 'operation_id', 'transaction_id'])
    for value in (prop['property_id'], prop['issuer_id'], prop['approval_reference'], prop['registration_operation_id']):
        identifier(value)
    sha(prop['approval_digest']); sha(op['request_digest'])
    require(type(prop['schema_version']) is int and prop['schema_version'] == 1
            and type(op['schema_version']) is int and op['schema_version'] == 1)
    require(type(prop['approved_supply']) is int and 1 <= prop['approved_supply'] <= 9007199254740991
            and isinstance(prop['issue_price_minor'], str) and re.fullmatch('[1-9][0-9]{0,15}', prop['issue_price_minor'])
            and prop['currency'] == 'INR' and isinstance(prop['proposal_timestamp'],str) and bool(prop['proposal_timestamp']))
    require(prop['property_id'] == op['property_id'] == property_id
            and prop['registration_operation_id'] == op['operation_id'] == operation_id
            and prop['registered_by_msp'] == op['authorizing_msp'] == 'Org1MSP'
            and isinstance(prop['registered_by_principal'], str) and bool(prop['registered_by_principal'])
            and prop['registered_by_principal'] == op['authorizing_principal']
            and op['function'] == 'RegisterApprovedProperty'
            and isinstance(prop['registration_transaction_id'], str) and bool(prop['registration_transaction_id'])
            and prop['registration_transaction_id'] == op['original_transaction_id']
            and op['result'] == dict(property_id=property_id, operation_id=operation_id,
                                     transaction_id=op['original_transaction_id']), 'Registration records disagree')

def channel(value):
    return checks.channel(value)

def snapshot(value, deployment_id):
    fields(value, ['schema_version', 'deployment_id', 'channel', 'property_id', 'operation_id', 'cp_certificate_sha256', 'organizations'])
    require(type(value['schema_version']) is int and value['schema_version'] == 1
            and value['deployment_id'] == deployment_id and value['channel'] == PARAMS['channel'])
    identifier(value['property_id']); identifier(value['operation_id'])
    fields(value['cp_certificate_sha256'], ['Org1MSP', 'Org2MSP'])
    for pin in value['cp_certificate_sha256'].values(): sha(pin)
    fields(value['organizations'], ['1', '2'])
    for org in value['organizations'].values():
        fields(org, ['channel', 'definitions', 'basic', 'property', 'operation', 'info', APPROVAL_FIELD] + (list(ISSUANCE_FIELDS) if M42 else []))
        channel(org['channel'])
        defs = definitions({'chaincode_definitions': list(org['definitions'].values())})
        require(defs == org['definitions'])
        expected_definition(defs[PARAMS['chaincode']], PARAMS['current_version'], PARAMS['current_sequence'])
        assets(org['basic']); info(org['info'], False)
        records(org['property'], org['operation'], value['property_id'], value['operation_id'])
        approval(org[APPROVAL_FIELD], PARAMS['current_version'], PARAMS['current_sequence'])
        if M42: issuance_records(org)
    a, b = value['organizations'].values()
    for field in ('channel', 'definitions', 'basic', 'property', 'operation', 'info') + (ISSUANCE_FIELDS if M42 else ()):
        require(a[field] == b[field], 'Baseline organizations disagree')
    return value

def preserve(baseline, actual, upgraded):
    expected_definition(actual['organizations']['1']['definitions'][PARAMS['chaincode']], PARAMS['version'] if upgraded else PARAMS['current_version'], PARAMS['sequence'] if upgraded else PARAMS['current_sequence'])
    a, b = actual['organizations'].values()
    for field in ('channel', 'definitions', 'basic', 'property', 'operation', 'info') + (ISSUANCE_FIELDS if M42 else ()):
        require(a[field] == b[field], 'Organizations disagree')
    for org in ('1', '2'):
        old, new = baseline['organizations'][org], actual['organizations'][org]
        if M42: issuance_records(new)
        for field in ('basic', 'property', 'operation', APPROVAL_FIELD) + (ISSUANCE_FIELDS if M42 else ()):
            require(old[field] == new[field], 'Preservation mismatch: ' + field)
        require({k:v for k,v in old['definitions'].items() if k != PARAMS['chaincode']} ==
                {k:v for k,v in new['definitions'].items() if k != PARAMS['chaincode']}, 'Unexpected other-chaincode definition change')
        start, end = channel(old['channel']), channel(new['channel'])
        require(end['height'] >= start['height'], 'Channel height regressed')
        if end['height'] == start['height']: require(end == start, 'Hashes changed at baseline height')
        if upgraded: require(end['height'] > start['height'], 'Upgrade must advance ledger height')
        info(new['info'], upgraded)

class Runner:
    def __init__(self, network, release):
        self.network, self.release = network, release
        self.net = network / 'drunix-network/test-network'
        self.peer = network / 'build/bin/peer'
        self.evidence = Path(tempfile.mkdtemp(prefix='upgrade-evidence-', dir=release))
        self.count = 0
        # Do not inherit peer overrides, connection profiles, proxy settings or application secrets.
        self.env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'GOCACHE', 'GOMODCACHE', 'TMPDIR')}
        self.env.update(FABRIC_CFG_PATH=str(network/'drunix-network/config'), CORE_PEER_TLS_ENABLED='true', FABRIC_LOGGING_SPEC='info')

    def env_for(self, org, lite=False, application=False):
        port = {('1', False):7061, ('2', False):9061, ('1', True):7051, ('2', True):9051}[(org, lite)]
        signer = '1' if application else org
        user = 'User1' if application else 'Admin'
        msp = self.net / f'organizations/peerOrganizations/org{signer}.example.com/users/{user}@org{signer}.example.com/msp'
        require(msp.is_dir(), 'Configured existing MSP directory missing')
        return dict(self.env, CORE_PEER_LOCALMSPID=f'Org{signer}MSP', CORE_PEER_MSPCONFIGPATH=str(msp),
            CORE_PEER_TLS_ROOTCERT_FILE=str(self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'),
            CORE_PEER_ADDRESS=f'localhost:{port}', CORE_PEER_TLS_SERVERHOSTOVERRIDE=f'peer{0 if lite else 1}.org{org}.example.com')

    def run(self, args, env=None, cwd=None, timeout=30):
        self.count += 1
        # Raw diagnostics remain private external evidence, never console/Git.
        with (self.evidence/f'{self.count:03}.stdout').open('xb') as out, (self.evidence/f'{self.count:03}.stderr').open('xb') as err:
            try:
                result = subprocess.run([str(a) for a in args], env=env or self.env, cwd=cwd,
                                        stdout=out, stderr=err, timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                raise CommandTimeout('UNKNOWN: command timed out; inspect private evidence, no retry') from None
            except OSError:
                raise Stop('UNKNOWN: command unavailable; inspect private evidence, no retry') from None
        stdout = (self.evidence/f'{self.count:03}.stdout').read_text()
        if result.returncode != 0:
            raise CLIRejected(result.returncode, stdout, (self.evidence/f'{self.count:03}.stderr').read_text())
        return stdout

    def query(self, args, org='1', lite=False, application=False):
        return checks.parse_json(self.run([self.peer]+args, self.env_for(org, lite, application)))

    def pins(self):
        pins = {}
        for org in ('1', '2'):
            cert = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
            pins['Org'+org+'MSP'] = hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert.read_text())).hexdigest()
        return pins

    def height(self, org):
        text = self.run([self.peer, 'channel', 'getinfo', '-c', PARAMS['channel']], self.env_for(org))
        require(text.startswith('Blockchain info: '))
        return channel(checks.parse_json(text[len('Blockchain info: '):]))

    def approval(self, org, sequence, version, package_id=None):
        value = self.query(['lifecycle','chaincode','queryapproved','-C',PARAMS['channel'],'--name',PARAMS['chaincode'],'--sequence',str(sequence),'--output','json'], org)
        approval(value, version, sequence, package_id)
        return {**value, 'init_required': value.get('init_required', False)}

    def observe_desired_approval(self, org, package_id):
        try:
            value = self.query(['lifecycle','chaincode','queryapproved','-C',PARAMS['channel'],'--name',PARAMS['chaincode'],
                                '--sequence',str(PARAMS['sequence']),'--output','json'], org)
        except CLIRejected as error:
            # This exact source-reviewed error means ABSENT OR INCOMPLETE, never
            # verified absence. Only explicit desired-state repair may proceed.
            message = ("query failed with status: 500 - failed to invoke backing implementation of "
                       "'QueryApprovedChaincodeDefinition': could not fetch approved chaincode definition "
                       f"(name: '{PARAMS['chaincode']}', sequence: '{PARAMS['sequence']}') on channel '{PARAMS['channel']}'")
            require(error.returncode == 1 and not error.stdout.strip() and
                    error.stderr.strip() in (message, 'Error: '+message),
                    'UNKNOWN: unrecognized approval-query failure; no approval authorized')
            return dict(state='UNKNOWN',reason='Native query cannot distinguish absence from partial state',repair_supported=True)
        inspect.definition(value, False)
        require(value['sequence'] == PARAMS['sequence'], 'Approval query returned an unexpected sequence')
        # Native encoding/json omits false init_required. Compare the same
        # canonical lifecycle record as approval(), without changing its meaning.
        value = {**value, 'init_required': value.get('init_required', False)}
        # Unknown/malformed JSON/source shapes stop; a valid unavailable source
        # is a known native representation that the explicit repair can replace.
        source = value.get('source'); fields(source, ['Type'])
        source = source['Type']
        if isinstance(source, dict) and set(source) == {'Unavailable'}:
            fields(source['Unavailable'], [])
            return dict(state='INCOMPLETE',observed=value,reason='Native package source is unavailable',repair_supported=True)
        fields(source, ['LocalPackage']); fields(source['LocalPackage'], ['package_id'])
        inspect.package(source['LocalPackage']['package_id'])
        try:
            approval(value, PARAMS['version'], PARAMS['sequence'], package_id)
        except Stop:
            return dict(state='CONFLICT',observed=value,repair_supported=True)
        return dict(state='MATCH', observed=value)

    def capture(self, deployment_id, property_id, operation_id):
        result = dict(schema_version=1, deployment_id=deployment_id, channel=PARAMS['channel'],
            property_id=identifier(property_id), operation_id=identifier(operation_id), cp_certificate_sha256=self.pins(), organizations={})
        before = {org:self.height(org) for org in ('1','2')}
        require(before['1'] == before['2'], 'Committing peers disagree')
        for org in ('1','2'):
            defs = definitions(self.query(['lifecycle','chaincode','querycommitted','-C',PARAMS['channel'],'--output','json'], org))
            lite = definitions(self.query(['lifecycle','chaincode','querycommitted','-C',PARAMS['channel'],'--output','json'], org, True))
            require(defs == lite, 'Lite/Committing peer definitions disagree')
            query = lambda cc, args, app=False: self.query(['chaincode','query','-C',PARAMS['channel'],'-n',cc,'-c',json.dumps({'Args':args})], org, True, app)
            prop = query(PARAMS['chaincode'], ['GetRegisteredProperty',property_id], True)
            op = query(PARAMS['chaincode'], ['GetOperation','Org1MSP',operation_id], True)
            records(prop, op, property_id, operation_id)
            result['organizations'][org] = dict(channel=before[org], definitions=defs,
                basic=assets(query('basic',['GetAllAssets'])), property=prop, operation=op,
                info=query(PARAMS['chaincode'],['GetContractInfo'], True))
            result['organizations'][org][APPROVAL_FIELD] = self.approval(org,PARAMS['current_sequence'],PARAMS['current_version'])
            if M42:
                row = result['organizations'][org]
                row['issuance'] = query(PARAMS['chaincode'],['GetIssuanceState',property_id], True)
                row['issuer_balance'] = query(PARAMS['chaincode'],['GetBalance',property_id,prop['issuer_id']], True)
                row['issuance_operation'] = query(PARAMS['chaincode'],['GetIssuanceOperation',ISSUANCE_ID], True)
                issuance_records(row)
        require(before == {org:self.height(org) for org in ('1','2')}, 'Channel changed during snapshot; stop for review')
        return result

    def installed(self, org, package_id):
        value = self.query(['lifecycle','chaincode','queryinstalled','--output','json'], org, True)
        result = inspect.installed(value, package_id)
        require(result in (inspect.MATCH, inspect.ABSENT), 'Conflicting or invalid installation state')
        return result

    def ready(self):
        args = definition_args()
        for org in ('1','2'):
            readiness(self.query(['lifecycle','chaincode','checkcommitreadiness']+args+['--output','json'], org))

    def mutate_once(self, phase, args, env, binding, authorization=None):
        marker = self.release / ('attempt-' + phase + '.json')
        require(not marker.exists(), 'Prior mutation attempt exists; inspect outcome, do not repeat')
        # Durable UNKNOWN intent precedes process creation. Never overwritten/deleted,
        # even if the process dies before/after acknowledgement. Later inspection is separate.
        intent = dict(state='UNKNOWN', phase=phase, context_sha256=binding,
                      note='One lifecycle attempt authorized; outcome requires independent inspection')
        if authorization is not None:
            intent['desired_state_authorization'] = authorization
            intent['command_evidence_directory'] = str(self.evidence)
        save(marker, intent)
        self.run(args, env, timeout=60)
        save(self.release/('acknowledged-'+phase+'.json'), dict(state='ACKNOWLEDGED_NOT_VERIFIED', context_sha256=binding))

    def tls_commit(self):
        for org in ('1','2'):
            cert = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
            ca = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'
            self.run(['openssl','x509','-in',cert,'-noout','-checkhost','localhost'])
            self.run(['openssl','x509','-in',cert,'-noout','-checkend','0'])
            self.run(['openssl','verify','-CAfile',ca,cert])

    def tls_approval(self, org):
        self.tls_commit()
        cert = self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
        self.run(['openssl','x509','-in',cert,'-noout','-checkhost',f'peer1.org{org}.example.com'])

    def approval_environment(self, org):
        env = self.env_for(org)
        expected = dict(CORE_PEER_LOCALMSPID=f'Org{org}MSP',
            CORE_PEER_MSPCONFIGPATH=str(self.net/f'organizations/peerOrganizations/org{org}.example.com/users/Admin@org{org}.example.com/msp'),
            CORE_PEER_ADDRESS='localhost:'+('7061' if org == '1' else '9061'),
            CORE_PEER_TLS_ROOTCERT_FILE=str(self.net/f'organizations/peerOrganizations/org{org}.example.com/peers/peer0.org{org}.example.com/tls/ca.crt'),
            CORE_PEER_TLS_SERVERHOSTOVERRIDE=f'peer1.org{org}.example.com',CORE_PEER_TLS_ENABLED='true')
        require(all(env.get(k) == v for k,v in expected.items()), 'Incorrect organization Admin/CP/TLS environment')
        return env


def definition_args():
    return ['--channelID',PARAMS['channel'],'--name',PARAMS['chaincode'],'--version',PARAMS['version'],'--sequence',str(PARAMS['sequence']),
            '--signature-policy',PARAMS['policy'],'--endorsement-plugin','escc','--validation-plugin','vscc','--init-required=false']

def orderer_args(runner):
    return ['-o','localhost:7050','--ordererTLSHostnameOverride','orderer.example.com','--tls','--cafile',
        str(runner.net/'organizations/ordererOrganizations/example.com/orderers/orderer.example.com/tls/ca.crt')]


def context(path, expected_sha, deployment_id):
    path = external(str(path)); private(path); private(path.parent, True)
    require(digest(path) == sha(expected_sha), 'Reviewed context hash mismatch')
    m = checks.load(path)
    fields(m, set(PARAMS) | {'schema_version','deployment_id','network_root','release_directory','package_path','package_sha256',
        'package_id','package_identity_path','package_identity_sha256','baseline_path','baseline_sha256','cp_certificate_sha256','source_revision'})
    require(type(m['schema_version']) is int and m['schema_version'] == 1 and m['deployment_id'] == release_id(deployment_id))
    require(all(type(m[k]) is type(v) and m[k] == v for k,v in PARAMS.items()), 'Unreviewed lifecycle parameters')
    network = external(m['network_root'])
    release = external(m['release_directory'], network); private(release, True)
    require(path.parent == release, 'Context must belong to its release directory')
    for key in ('package_path','baseline_path','package_identity_path'):
        p = external(m[key], network); private(p)
        require(p.parent == release and digest(p) == sha(m[key.replace('_path','_sha256')]), 'Release input hash/path mismatch')
    require(m['package_id'] == package_label()+':' + m['package_sha256'], 'Unexpected package identity')
    identity = checks.load(m['package_identity_path'])
    fields(identity, ['schema_version','deployment_id','source_revision','source_files','package_sha256','package_id','package_size_bytes','label'])
    require(type(identity['schema_version']) is int and identity['schema_version'] == 1
            and identity['deployment_id'] == deployment_id and identity['source_revision'] == m['source_revision']
            and isinstance(m['source_revision'],str) and re.fullmatch('[0-9a-f]{40}',m['source_revision'])
            and identity['package_id'] == m['package_id'] and identity['package_sha256'] == m['package_sha256']
            and identity['label'] == package_label() and type(identity['package_size_bytes']) is int
            and identity['package_size_bytes'] == Path(m['package_path']).stat().st_size)
    require(isinstance(identity['source_files'],dict) and ({'go.mod','go.sum','main.go','contract/issuance.go'} | ({'contract/transfer.go'} if M42 else set())) <= identity['source_files'].keys())
    for name, value in identity['source_files'].items():
        require(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts)
        sha(value)
    baseline = snapshot(checks.load(m['baseline_path']), deployment_id)
    require(m['cp_certificate_sha256'] == baseline['cp_certificate_sha256'])
    return m, baseline, network, release


def execute(phase, runner, m, baseline, binding, authorization_flags=None):
    independent = phase.startswith('verify-approval-')
    count = len(verification_files(runner.release,phase[-1])) if independent else 0
    try:
        return execute_phase(phase,runner,m,baseline,binding,authorization_flags)
    except (Stop,SystemExit,OSError,ValueError,TypeError,KeyError,AttributeError):
        # A failed independent verification must not leave an older MATCH as
        # the latest observation. Never overwrite prior observations.
        if independent and len(verification_files(runner.release,phase[-1])) == count:
            save_approval_verification(runner,m,binding,phase[-1],
                dict(state='UNKNOWN',reason='Independent verification failed'),None,False,
                dict(transaction_validation='UNKNOWN',limitation='Verification unavailable'))
        raise

def execute_phase(phase, runner, m, baseline, binding, authorization_flags=None):
    authorization = desired_state_authorization(phase, m, binding, authorization_flags) if authorization_flags is not None else None
    require(runner.pins() == m['cp_certificate_sha256'], 'Local network certificate binding mismatch')
    require(runner.run([runner.peer,'lifecycle','chaincode','calculatepackageid',m['package_path']]).strip() == m['package_id'])
    actual = runner.capture(m['deployment_id'],baseline['property_id'],baseline['operation_id'])
    current = actual['organizations']['1']['definitions'][PARAMS['chaincode']]
    upgraded = current['version'] == PARAMS['version'] and current['sequence'] == PARAMS['sequence']
    preserve(baseline, actual, upgraded)
    save(runner.evidence/'snapshot.json', actual)
    org = phase[-1] if phase[-1:] in ('1','2') else None
    if phase.startswith('install-'):
        if runner.installed(org,m['package_id']) == inspect.MATCH:
            print('MATCH: reviewed package installed; no mutation'); return
        require(not upgraded, 'Already upgraded; missing installation requires independent review')
        runner.mutate_once(phase,[runner.peer,'lifecycle','chaincode','install',m['package_path']],runner.env_for(org,True),binding)
        print('Installation command acknowledged; STOP. Inspect installation separately.'); return
    if phase.startswith('approve-'):
        require(runner.installed(org,m['package_id']) == inspect.MATCH, 'Package not installed')
        if authorization is not None:
            require(not upgraded, 'Desired-state approval requires the reviewed previous definition')
            observation = runner.observe_desired_approval(org, m['package_id'])
            save(runner.evidence/'prior-approval.json', observation)
            if observation['state'] == 'MATCH':
                print('MATCH: desired approval already observed; no submission and no attribution to a prior attempt.'); return
            require(not (runner.release/('attempt-'+phase+'.json')).exists(),
                    'Prior approval attempt exists; outcome UNKNOWN, no resubmission authorized')
            require(not (runner.release/'attempt-commit.json').exists(),
                    'Known commit attempt may be in flight; independent recovery review required')
            other = '2' if org == '1' else '1'
            if (runner.release/('attempt-approve-org'+other+'.json')).exists():
                observed_other = runner.approval(other,PARAMS['sequence'],PARAMS['version'],m['package_id'])
                require_verification(runner,m,binding,other,observed_other,actual['organizations'][other]['channel'])
            require(observation.get('repair_supported') is True,
                    'Unsupported partial/unknown state; no desired-state mutation authorized')
            print('Prior approval: '+observation['state']+'; explicit replacement/repair authorization applies. Absence is not established.')
            runner.tls_approval(org)
            final = runner.capture(m['deployment_id'],baseline['property_id'],baseline['operation_id'])
            preserve(baseline,final,False)
            require(final['organizations']['1']['channel'] == actual['organizations']['1']['channel'],
                    'Unexpected channel change during approval inspection')
            require(digest(m['package_path']) == m['package_sha256'], 'Reviewed package changed before approval')
            # Revalidate the explicit acknowledgement immediately before saving
            # its durable intent; a changed file is never silently authorized.
            authorization = desired_state_authorization(phase, m, binding, authorization_flags)
            env = runner.approval_environment(org)
            args = [runner.peer,'lifecycle','chaincode','approveformyorg']+orderer_args(runner)+definition_args()
            args += ['--package-id',m['package_id'],'--peerAddresses',env['CORE_PEER_ADDRESS'],
                     '--tlsRootCertFiles',env['CORE_PEER_TLS_ROOTCERT_FILE'],'--waitForEvent','--waitForEventTimeout','30s']
            runner.mutate_once(phase,args,env,binding,authorization)
            # No post-approval query, preservation snapshot, readiness or other
            # phase is chained from the mutation. Verification is separately authorized.
            print('ACKNOWLEDGED_NOT_VERIFIED: one native approval command returned. STOP; independently authorize verify-approval-org'+org+'.'); return
        runner.approval(org,PARAMS['sequence'],PARAMS['version'],m['package_id'])
        print('MATCH: exact target approval exists; inspection only, no mutation.'); return
    if phase.startswith('verify-approval-'):
        require(not upgraded, 'Approval verification requires the reviewed previous definition')
        require(runner.installed(org,m['package_id']) == inspect.MATCH, 'Package not installed')
        runner.approval_environment(org)
        verify_approval(runner,m,baseline,binding,org,actual)
        return
    for member in ('1','2'):
        require(runner.installed(member,m['package_id']) == inspect.MATCH, 'Package not installed')
        observed = runner.approval(member,PARAMS['sequence'],PARAMS['version'],m['package_id'])
        if phase in ('readiness','commit'):
            require_verification(runner,m,binding,member,observed,actual['organizations'][member]['channel'])
    if phase == 'verify':
        require(upgraded, 'Target definition not committed')
        print('PASS: both CPs/LPs agree; target definition, approvals, installations and preserved records verified.'); return
    require(not upgraded, 'Target already committed; use separately authorized verify')
    runner.ready()
    if phase == 'readiness':
        print('PASS: exact approvals/readiness; STOP. Commit is not authorized.'); return
    require(phase == 'commit')
    runner.tls_commit()
    # Final fresh preservation/definition inspection immediately before mutation.
    final = runner.capture(m['deployment_id'],baseline['property_id'],baseline['operation_id'])
    preserve(baseline,final,False)
    require(final['organizations']['1']['channel'] == actual['organizations']['1']['channel'],
            'Unexpected channel change during commit inspection')
    env = runner.env_for('1'); env.pop('CORE_PEER_TLS_SERVERHOSTOVERRIDE')
    args = [runner.peer,'lifecycle','chaincode','commit']+orderer_args(runner)+definition_args()
    for member,port in (('1',7061),('2',9061)):
        args += ['--peerAddresses',f'localhost:{port}','--tlsRootCertFiles',str(runner.net/f'organizations/peerOrganizations/org{member}.example.com/peers/peer0.org{member}.example.com/tls/ca.crt')]
    runner.mutate_once(phase,args+['--waitForEvent','--waitForEventTimeout','30s'],env,binding)
    print('Commit command acknowledged, not independently verified. STOP; authorize verify separately.')


def prepare_package(runner, deployment_id, revision):
    def run(operation, args, env=None, cwd=None, timeout=30):
        try:
            return runner.run(args, env, cwd, timeout)
        except Stop as error:
            reason = 'timed out' if isinstance(error, CommandTimeout) else 'failed or unavailable'
            # Labels are fixed locally; never echo arguments, environment or raw CLI errors.
            raise Stop(f'Offline packaging: {operation} {reason}; subprocess deadline={timeout}s; '
                       f'command={runner.count:03}; private evidence={runner.evidence}; STOP, no retry') from None

    require(run('branch inspection',['git','branch','--show-current'],cwd=REPO).strip() == 'feat/frontend-connected-mode')
    require(run('revision inspection',['git','rev-parse','HEAD'],cwd=REPO).strip() == revision and re.fullmatch('[0-9a-f]{40}',revision))
    require(not run('working-tree inspection',['git','status','--porcelain'],cwd=REPO).strip(), 'Reviewed source must be committed and clean before packaging')
    identity_path = runner.release/'package-identity.json'
    require(not any((runner.release/name).exists() for name in ('package-identity.json',(package_label()+'.tar.gz'),'reproducibility-check.tar.gz','validated-chaincode','staged-chaincode')), 'Do not overwrite a release')
    root = REPO/'chaincode/tokansh'
    paths = run('source inventory',['git','ls-files','chaincode/tokansh'],cwd=REPO).splitlines()
    staged = runner.release/'staged-chaincode'; staged.mkdir(mode=0o700)
    hashes = {}
    for name in paths:
        source = REPO/name
        require(source.is_file() and not source.is_symlink())
        relative = source.relative_to(root)
        require(not any(c in str(relative) for c in '\0\r\n'))
        target = staged/relative; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target); hashes[str(relative)] = digest(source)
    require('contract/issuance.go' in hashes and (not M42 or 'contract/transfer.go' in hashes), 'Reviewed M4 source missing')
    env = dict(runner.env,GOTOOLCHAIN='local',GOPROXY='off',GOSUMDB='off',GOFLAGS='-mod=readonly')
    run('Go vendoring',['go','mod','vendor'],env,staged,120)
    require(digest(staged/'go.mod') == hashes['go.mod'] and digest(staged/'go.sum') == hashes['go.sum'])
    env['GOFLAGS'] = '-mod=vendor'
    for operation, args, timeout in (
        # The Go test deadline does not bound compilation/linking.
        ('Go unit tests',['go','test','-count=1','-timeout=60s','./...'],600),
        ('Go race tests',['go','test','-race','-count=1','-timeout=60s','./...'],600),
        ('Go vet',['go','vet','./...'],180),
        ('Go build',['go','build','-o',str(runner.release/'validated-chaincode'),'.'],180)):
        run(operation,args,env,staged,timeout)
    package = runner.release/(package_label()+'.tar.gz')
    repeat = runner.release/'reproducibility-check.tar.gz'
    for destination in (package,repeat):
        run('chaincode package',[runner.peer,'lifecycle','chaincode','package',destination,'--path',staged,'--lang','golang','--label',package_label()])
    require(digest(package) == digest(repeat), 'Packaging was not reproducible')
    package_id = run('package identity',[runner.peer,'lifecycle','chaincode','calculatepackageid',package]).strip()
    require(package_id == package_label()+':'+digest(package))
    require(all(digest(staged/name) == value for name,value in hashes.items()), 'Staged reviewed source changed')
    require(not run('final working-tree inspection',['git','status','--porcelain'],cwd=REPO).strip(), 'Source repository changed during packaging')
    save(identity_path,dict(schema_version=1,deployment_id=deployment_id,source_revision=revision,source_files=hashes,
        package_sha256=digest(package),package_id=package_id,package_size_bytes=package.stat().st_size,label=package_label()))
    print('PASS: staged tests/build and reproducible package. Review package-identity.json; no installation performed.')


def main(argv=None):
    os.umask(0o077)
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['--m42']:
        configure_m42()
        argv.pop(0)
    elif argv[:1] == ['--transition']:
        require(len(argv) >= 5, 'Transition requires current version, current sequence, target version and target sequence')
        transition = argv[1:5]
        cursor = 5
        options = {'channel': 'mychannel', 'chaincode': 'tokansh', 'policy': POLICY}
        option_names = {'--channel': 'channel', '--chaincode': 'chaincode', '--policy': 'policy'}
        while cursor < len(argv) and argv[cursor] in option_names:
            require(cursor + 1 < len(argv), 'Transition option requires a value')
            options[option_names[argv[cursor]]] = argv[cursor + 1]
            cursor += 2
        configure_next_transition(transition[0], int(transition[1]), transition[2], int(transition[3]), **options)
        argv = argv[cursor:]
    require(len(argv) >= 2 and argv[0] in PHASES and argv[1] == '--authorize-'+argv[0],
            'Exactly one phase and its explicit organization-specific acknowledgement are required')
    options = [token.split('=',1)[0] for token in argv[2:] if token.startswith('--')]
    require(len(options) == len(set(options)), 'Duplicate CLI options are ambiguous')
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument('phase',choices=PHASES)
    for name in ('context','context-sha256','deployment-id','network-root','release-directory','source-revision',
                 'property-id','operation-id','preservation-baseline','preservation-sha256'):
        p.add_argument('--'+name)
    p.add_argument('--desired-state-authorization')
    p.add_argument('--authorization-sha256')
    p.add_argument('--acknowledge-replacement-and-repair')
    p.add_argument('--acknowledge-maintenance-window')
    args = p.parse_args([argv[0]] + argv[2:])
    authorization_flags = None
    flags = (args.desired_state_authorization, args.authorization_sha256, args.acknowledge_replacement_and_repair,args.acknowledge_maintenance_window)
    if any(value is not None for value in flags):
        require(args.phase in ('approve-org1','approve-org2') and all(value is not None for value in flags),
                'Approval requires its file, reviewed hash, replacement/repair and maintenance-window acknowledgements together')
        authorization_flags = dict(path=flags[0],sha256=flags[1],acknowledgement=flags[2],maintenance_acknowledgement=flags[3])
    deployment_id = release_id(args.deployment_id)
    if args.phase in ('preflight','package'):
        require(not args.context and not args.context_sha256, 'Do not reuse an old deployment context')
        network = external(args.network_root); release = external(args.release_directory,network)
        private(release,True)
        m = baseline = None
    else:
        m,baseline,network,release = context(args.context,args.context_sha256,deployment_id)
    # Local advisory lock only; trusted operator/filesystem remains the boundary.
    lock_fd = os.open(release/'upgrade.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, 'a') as lock:
        private(release/'upgrade.lock')
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise Stop('Another release phase is running') from None
        runner = Runner(network,release)
        print('Phase='+args.phase+'; private evidence='+str(runner.evidence))
        if args.phase == 'package':
            prepare_package(runner,deployment_id,args.source_revision)
        elif args.phase == 'preflight':
            require(not (release/'baseline.json').exists(), 'Never replace the reviewed baseline')
            initial = external(args.preservation_baseline,network); private(initial)
            require(digest(initial) == sha(args.preservation_sha256), 'Accepted preservation baseline hash mismatch')
            old = checks.load(initial)
            current = snapshot(runner.capture(deployment_id,args.property_id,args.operation_id),deployment_id)
            recovered = None
            if isinstance(old,dict) and old.get('kind') == 'NEWLY_OBSERVED_M3_BASELINE':
                recovered = module('recover-m3-baseline').validate_accepted(initial,args.preservation_sha256)
                require(recovered['cp_certificate_sha256'] == current['cp_certificate_sha256'],
                        'Recovered baseline environment mismatch')
                if M42:
                    for org in ('1','2'):
                        for field in ('property','operation'):
                            require(recovered['organizations'][org][field] == current['organizations'][org][field],
                                    'Accepted registration baseline mismatch: '+field)
                else:
                    preserve(recovered,current,False)
                # Adapt only after acceptance/full M3 preservation validation;
                # retain the existing historical basic/channel checks below.
                old = {f'Org{org}_{field}':dict(observed=value) for org,row in recovered['organizations'].items()
                       for field,value in (('channel',row['channel']),('basic',row['basic']),
                                           ('definitions',dict(chaincode_definitions=list(row['definitions'].values()))))}
            for org in ('1','2'):
                previous = checks.named_definition(old['Org'+org+'_definitions']['observed'],'basic')
                require({**previous,'init_required':previous.get('init_required',False)} == current['organizations'][org]['definitions']['basic'])
                require(assets(old['Org'+org+'_basic']['observed']) == current['organizations'][org]['basic'], 'Accepted basic baseline mismatch')
                start,end = channel(old['Org'+org+'_channel']['observed']),current['organizations'][org]['channel']
                require(end['height'] >= start['height'])
                if end['height'] == start['height']: require(end == start)
            if recovered is not None:
                save(release/'baseline-provenance.json',dict(kind='NEWLY_OBSERVED_M3_BASELINE',
                     accepted_baseline_path=str(initial),accepted_baseline_sha256=args.preservation_sha256))
            save(release/'baseline.json',current)
            print('PASS: read-only preflight captured; review and freeze baseline hash before selecting a context.')
        else:
            execute(args.phase,runner,m,baseline,args.context_sha256,authorization_flags)
    print('STOP. No following phase is implicitly authorized.')

if __name__ == '__main__':
    try:
        main()
    except (Stop,SystemExit,OSError,ValueError,TypeError,KeyError,AttributeError) as error:
        if isinstance(error,SystemExit) and error.code == 0: raise
        print('STOP: '+(str(error) if isinstance(error,Stop) else 'Invalid input or inspection; no further mutation authorized'),file=sys.stderr)
        sys.exit(1)
