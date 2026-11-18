"""Offline validation of an externally reviewed deployment context. No peer calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import ssl
import sys

HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
spec = importlib.util.spec_from_file_location('checks', HERE / 'deployment-checks.py')
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def external(value):
    checks.require(isinstance(value, str) and value.startswith('/') and not any(c in value for c in '\n\r\0'), 'Expected absolute external path')
    path = Path(value).resolve()
    checks.require(not path.is_relative_to(REPOSITORY), 'Runtime artifacts must be outside the repository')
    return path


def digest(value):
    checks.require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None, 'Expected SHA-256')
    return value


def validate(path, expected_sha, expected_id):
    path = external(str(path))
    checks.require(sha(path) == digest(expected_sha), 'Manifest digest mismatch')
    m = checks.load(path)
    fields = {'schema_version', 'deployment_id', 'network_root', 'package_path', 'package_sha256',
              'package_id', 'baseline_path', 'baseline_sha256', 'evidence_directory',
              'cp_certificate_sha256', 'channel', 'chaincode', 'version', 'sequence', 'policy', 'init_required'}
    checks.require(isinstance(m, dict) and set(m) == fields, 'Incomplete or unexpected manifest fields')
    checks.require(type(m['schema_version']) is int and m['schema_version'] == 1, 'Manifest schema mismatch')
    checks.require(isinstance(m['deployment_id'], str) and re.fullmatch('[a-zA-Z0-9_-]{8,80}', m['deployment_id']) is not None and m['deployment_id'] == expected_id, 'Deployment ID mismatch')
    # This procedure is reviewed for initial v1 only. Upgrades require a new review.
    checks.require(m['channel'] == 'mychannel' and m['chaincode'] == 'tokansh' and m['version'] == '1.0'
                   and type(m['sequence']) is int and m['sequence'] == 1 and m['init_required'] is False
                   and m['policy'] == "AND('Org1MSP.peer','Org2MSP.peer')", 'Unreviewed lifecycle parameters')
    network = external(m['network_root'])
    checks.require(not path.is_relative_to(network), 'Manifest must be outside DRUNIX repository')
    package, baseline, evidence = (external(m[k]) for k in ('package_path', 'baseline_path', 'evidence_directory'))
    checks.require(all(not p.is_relative_to(network) for p in (package, baseline, evidence)), 'Runtime artifacts must be outside DRUNIX repository')
    checks.require(evidence.is_dir(), 'Evidence directory must already exist')
    checks.require(sha(package) == digest(m['package_sha256']), 'Package digest mismatch')
    checks.require(m['package_id'] == 'tokansh_1.0:' + m['package_sha256'], 'Package ID mismatch')
    checks.require(sha(baseline) == digest(m['baseline_sha256']), 'Baseline digest mismatch')
    b = checks.load(baseline)
    channels = []
    for org in (1, 2):
        channels.append(checks.channel(b[f'Org{org}_channel']['observed']))
        checks.named_definition(b[f'Org{org}_definitions']['observed'], 'basic')
        assets = b[f'Org{org}_basic']['observed']
        checks.require(isinstance(assets, list) and len(assets) == 6 and len({a['ID'] for a in assets}) == 6, 'Expected six distinct baseline assets')
    checks.require(channels[0] == channels[1] and b['Org1_basic']['observed'] == b['Org2_basic']['observed'], 'Baseline organizations disagree')
    pins = m['cp_certificate_sha256']
    checks.require(isinstance(pins, dict) and set(pins) == {'Org1MSP', 'Org2MSP'}, 'Missing environment certificate pins')
    for org in (1, 2):
        cert = network / f'drunix-network/test-network/organizations/peerOrganizations/org{org}.example.com/peers/peer1.org{org}.example.com/tls/server.crt'
        der = ssl.PEM_cert_to_DER_cert(cert.read_text())
        checks.require(hashlib.sha256(der).hexdigest() == digest(pins[f'Org{org}MSP']), 'Network certificate binding mismatch')
    return [str(network), str(package), str(baseline), m['package_sha256'], m['package_id'], str(evidence)]


def main():
    checks.require(len(sys.argv) == 4, 'Usage: MANIFEST REVIEWED_SHA256 DEPLOYMENT_ID')
    try:
        print('\n'.join(validate(*sys.argv[1:])))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise SystemExit('Validation failed: malformed deployment context or missing local input') from None


if __name__ == '__main__':
    main()
