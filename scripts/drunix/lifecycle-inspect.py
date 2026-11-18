"""Strict offline lifecycle inspection. Exit 0 MATCH, 3 ABSENT, 4 CONFLICT, 1 INVALID.

No CLI failure is absence. In particular DRUNIX queryapproved cannot distinguish
missing approval from inconsistent approval/source state; both must stop.
"""
import base64
import importlib.util
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location('checks', Path(__file__).with_name('deployment-checks.py'))
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)
MATCH, ABSENT, CONFLICT, INVALID = 0, 3, 4, 1
# Reviewed v1 ApplicationPolicy protobuf: AND(Org1MSP.peer, Org2MSP.peer).
POLICY = 'CiwSDBIKCAISAggAEgIIARoNEgsKB09yZzFNU1AQAxoNEgsKB09yZzJNU1AQAw=='
FIELDS = {'version', 'sequence', 'endorsement_plugin', 'validation_plugin', 'validation_parameter', 'collections'}


def require(ok):
    checks.require(ok, 'Malformed or ambiguous lifecycle inspection')


def text(value):
    require(isinstance(value, str) and bool(value))


def package(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]*:[0-9a-f]{64}', value) is not None)
    return value.split(':', 1)[0]


def installed(value, expected):
    label = package(expected)
    require(isinstance(value, dict) and set(value) == {'installed_chaincodes'})
    rows = value['installed_chaincodes']; require(isinstance(rows, list))
    ids, labels = set(), set()
    for row in rows:
        require(isinstance(row, dict) and {'package_id', 'label'} <= row.keys()
                and row.keys() <= {'package_id', 'label', 'references'})
        require(package(row['package_id']) == row['label'])
        require(row['package_id'] not in ids and row['label'] not in labels)
        ids.add(row['package_id']); labels.add(row['label'])
        if 'references' in row:
            refs = row['references']; require(isinstance(refs, dict))
            for channel, ref in refs.items():
                text(channel)
                require(isinstance(ref, dict) and set(ref) == {'chaincodes'} and isinstance(ref['chaincodes'], list))
                seen = set()
                for chaincode in ref['chaincodes']:
                    require(isinstance(chaincode, dict) and set(chaincode) == {'name', 'version'})
                    text(chaincode['name']); text(chaincode['version'])
                    identity = (chaincode['name'], chaincode['version'])
                    require(identity not in seen); seen.add(identity)
    if expected in ids: return MATCH
    return CONFLICT if label in labels else ABSENT


def definition(value, named):
    require(isinstance(value, dict) and FIELDS <= value.keys()
            and value.keys() <= FIELDS | {'init_required', 'name' if named else 'source'})
    if named: text(value['name'])
    require(type(value['sequence']) is int and value['sequence'] > 0)
    for key in ('version', 'endorsement_plugin', 'validation_plugin', 'validation_parameter'): text(value[key])
    require(bool(base64.b64decode(value['validation_parameter'], validate=True)))
    require(isinstance(value['collections'], dict))
    if 'init_required' in value: require(type(value['init_required']) is bool)
    return (value['version'] == '1.0' and value['sequence'] == 1
            and value['endorsement_plugin'] == 'escc' and value['validation_plugin'] == 'vscc'
            and value['validation_parameter'] == POLICY and value['collections'] == {}
            and value.get('init_required', False) is False)


def committed(value):
    require(isinstance(value, dict) and set(value) == {'chaincode_definitions'})
    rows = value['chaincode_definitions']; require(isinstance(rows, list))
    seen = set(); outcome = ABSENT
    for row in rows:
        matches = definition(row, True)
        require(row['name'] not in seen); seen.add(row['name'])
        if row['name'] == 'tokansh': outcome = MATCH if matches else CONFLICT
    return outcome


def approved(value, expected):
    package(expected)
    matches = definition(value, False)
    # encoding/json of the pinned Go protobuf oneof uses exported wrapper names,
    # not protojson's local_package shape. Unknown/unavailable sources fail closed.
    require('source' in value and isinstance(value['source'], dict) and set(value['source']) == {'Type'})
    source = value['source']['Type']
    require(isinstance(source, dict) and set(source) == {'LocalPackage'})
    local = source['LocalPackage']
    require(isinstance(local, dict) and set(local) == {'package_id'})
    package(local['package_id'])
    return MATCH if matches and local['package_id'] == expected else CONFLICT


def inspect(mode, value, expected):
    if mode == 'installed': return installed(value, expected)
    if mode == 'committed': return committed(value)
    if mode == 'approved': return approved(value, expected)
    require(False)


def main():
    try:
        require(len(sys.argv) == 4)
        result = inspect(sys.argv[1], checks.load(sys.argv[2]), sys.argv[3])
        print({MATCH: 'MATCH', ABSENT: 'ABSENT', CONFLICT: 'CONFLICT'}[result])
        return result
    except (SystemExit, OSError, ValueError, TypeError, KeyError, AttributeError):
        print('Validation failed: malformed or ambiguous lifecycle inspection; no mutation authorized.', file=sys.stderr)
        return INVALID


if __name__ == '__main__':
    sys.exit(main())
