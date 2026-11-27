"""Focused tests for later explicit TokANSH lifecycle transitions."""
import copy
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_upgrade_workflow as fixtures


def workflow():
    spec = importlib.util.spec_from_file_location(
        'upgrade_transition_workflow', Path(__file__).with_name('upgrade-workflow.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def structured_snapshot(u, deployment_id='historical-m42'):
    value = copy.deepcopy(fixtures.baseline(deployment_id))
    issuer = value['organizations']['1']['property']['issuer_id']
    for row in value['organizations'].values():
        row['definitions']['tokansh'] = fixtures.definition('1.2', 3)
        row['info'] = dict(contract='tokansh', schema_version=1,
                           functions=list(u.TRANSFER_FUNCTIONS),
                           supply_interpretation=u.LIFETIME_SUPPLY)
        row['approval_previous'] = fixtures.approved('tokansh_1.1:' + 'd' * 64, '1.1', 2)
        del row['approval_v1']
        row['issuance'] = dict(schema_version=1, property_id=value['property_id'], issuer_id=issuer,
                               approved_supply=100, cumulative_issued_supply=10,
                               remaining_issuance_capacity=90)
        row['issuer_balance'] = dict(schema_version=1, property_id=value['property_id'],
                                     holder_id=issuer, quantity=10)
        row['issuance_operation'] = dict(
            schema_version=1, operation_id='97000000-0000-4000-8000-000000000001',
            authorizing_msp='Org1MSP', authorizing_principal='test-only-principal',
            function='IssueANSH', request_digest='c' * 64,
            property_id=value['property_id'], issuer_id=issuer, quantity=10,
            original_transaction_id='a' * 64, result={})
    return value


def write_verified_evidence(u, directory, snapshot, report_overrides=None):
    snapshot_path = directory / 'historical-snapshot.json'
    report_path = directory / 'deployment-verification.json'
    u.save(snapshot_path, snapshot)
    report = dict(schema_version=1, result='PASS', deployment_id=snapshot['deployment_id'],
                  channel='mychannel', chaincode='tokansh', version='1.2', sequence=3,
                  snapshot_path=str(snapshot_path), snapshot_sha256=u.digest(snapshot_path),
                  previous_approval_version='1.1', previous_approval_sequence=2)
    if report_overrides:
        report.update(report_overrides)
    u.save(report_path, report)
    return report_path, snapshot_path


def write_transfer_reconciliation(u, directory, reference, actual, report,
                                  snapshot_path, overrides=None,
                                  evidence_overrides=None):
    evidence_directory = directory / 'transfer-evidence'
    evidence_directory.mkdir(mode=0o700)
    issuer = reference['organizations']['1']['issuer_balance']['holder_id']
    holders = {
        issuer: 2,
        '00000000-0000-4000-8000-000000000003': 2,
        '00000000-0000-4000-8000-000000000005': 2,
        '00000000-0000-4000-8000-000000000006': 4,
    }
    initial = {issuer: 10}
    transfers = [
        dict(block_number=19, transaction_id='b' * 64,
             operation_id='aea1bc2b-ee8f-4e57-b5fa-fb78b7cad0d6',
             validation_code=0, state='COMMITTED_VALID', chaincode='tokansh',
             function='TransferANSH', command=dict(property_id=reference['property_id'],
             from_holder_id=issuer, to_holder_id='00000000-0000-4000-8000-000000000003', quantity=4)),
        dict(block_number=20, transaction_id='c' * 64,
             operation_id='84b27162-c298-4646-b58b-de77e3665b22',
             validation_code=0, state='COMMITTED_VALID', chaincode='tokansh',
             function='TransferANSH', command=dict(property_id=reference['property_id'],
             from_holder_id='00000000-0000-4000-8000-000000000003',
             to_holder_id='00000000-0000-4000-8000-000000000005', quantity=2)),
        dict(block_number=21, transaction_id='d' * 64,
             operation_id='686e9759-fbf5-4200-8ec4-67bc434bd1ab',
             validation_code=0, state='COMMITTED_VALID', chaincode='tokansh',
             function='TransferANSH', command=dict(property_id=reference['property_id'],
             from_holder_id=issuer, to_holder_id='00000000-0000-4000-8000-000000000006', quantity=4)),
    ]
    for org in ('1', '2'):
        evidence = dict(schema_version=1, organization=org,
                        channel=actual['organizations'][org]['channel'],
                        transfers=transfers, final_balances=holders)
        if evidence_overrides and org in evidence_overrides:
            evidence.update(evidence_overrides[org])
        u.save(evidence_directory / ('org' + org + '.json'), evidence)
    evidence_hashes = {path.name: u.digest(path) for path in evidence_directory.iterdir()}
    value = dict(schema_version=1, kind='DRUNIX_TRANSFER_RECONCILIATION',
                 historical_snapshot_sha256=u.digest(snapshot_path),
                 historical_deployment_id=reference['deployment_id'],
                 historical_verification_sha256=report['verification_sha256'],
                 current_deployment_id=actual['deployment_id'], channel='mychannel',
                 chaincode='tokansh', property_id=reference['property_id'], issued_supply=10,
                 initial_balances=initial, final_balances=holders, transfers=transfers,
                 organizations={org: dict(channel=actual['organizations'][org]['channel'],
                                           transfers=transfers, final_balances=holders)
                                for org in ('1', '2')},
                 evidence_directory=str(evidence_directory), evidence_sha256=evidence_hashes)
    if overrides:
        value.update(overrides)
    path = directory / 'transfer-reconciliation.json'
    u.save(path, value)
    return path


class TransitionProfileTests(unittest.TestCase):
    def test_next_transition_binds_version_sequence_and_current_policy(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        self.assertEqual(u.PARAMS['current_version'], '1.2')
        self.assertEqual(u.PARAMS['current_sequence'], 3)
        self.assertEqual(u.PARAMS['version'], '1.3')
        self.assertEqual(u.PARAMS['sequence'], 4)
        self.assertEqual(u.FUNCTIONS, u.TRANSFER_FUNCTIONS)
        self.assertEqual(u.M4_FUNCTIONS, u.TRANSFER_FUNCTIONS)
        self.assertEqual(u.SOURCE_SUPPLY_INTERPRETATION, u.LIFETIME_SUPPLY)
        self.assertEqual(u.TARGET_SUPPLY_INTERPRETATION, u.ONE_TIME_SUPPLY)
        source = dict(contract='tokansh', schema_version=1, functions=u.FUNCTIONS,
                      supply_interpretation=u.LIFETIME_SUPPLY)
        target = dict(contract='tokansh', schema_version=1, functions=u.M4_FUNCTIONS,
                      supply_interpretation=u.ONE_TIME_SUPPLY)
        u.info(source, 'source')
        u.info(target, 'target')

    def test_captured_v12_metadata_is_accepted_as_source(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        captured = {
            'contract': 'tokansh',
            'schema_version': 1,
            'functions': list(u.TRANSFER_FUNCTIONS),
            'supply_interpretation': u.LIFETIME_SUPPLY,
        }
        u.info(captured, 'source')

    def test_target_profile_is_explicit_and_not_reused_for_source(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        source = dict(contract='tokansh', schema_version=1,
                      functions=list(u.TRANSFER_FUNCTIONS),
                      supply_interpretation=u.LIFETIME_SUPPLY)
        target = dict(contract='tokansh', schema_version=1,
                      functions=list(u.TRANSFER_FUNCTIONS),
                      supply_interpretation=u.ONE_TIME_SUPPLY)
        u.info(source, 'source')
        u.info(target, 'target')
        with self.assertRaisesRegex(u.Stop, 'supply_interpretation'):
            u.info(target, 'source')

    def test_invalid_sequence_transitions_fail_closed(self):
        for current, target in ((3, 3), (3, 5), (0, 1), (True, 2)):
            u = workflow()
            with self.subTest(current=current, target=target), self.assertRaises(u.Stop):
                u.configure_next_transition('1.2', current, '1.3', target)

    def test_unreviewed_chaincode_or_policy_is_rejected(self):
        for kwargs in ({'chaincode': 'basic'}, {'policy': 'AND(Org1MSP.peer)'}):
            u = workflow()
            with self.subTest(kwargs=kwargs), self.assertRaises(u.Stop):
                u.configure_next_transition('1.2', 3, '1.3', 4, **kwargs)

    def test_historical_metadata_cannot_prove_new_target(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        historical = dict(contract='tokansh', schema_version=1,
                          functions=copy.deepcopy(u.FUNCTIONS),
                          supply_interpretation=u.LIFETIME_SUPPLY)
        with self.assertRaises(u.Stop):
            u.info(historical, 'target')

    def test_next_transition_preserves_arbitrary_existing_issuance_observations(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        property_id = 'f6169750-4676-4e99-887f-2bc5471bd520'
        issuer_id = '00000000-0000-4000-8000-000000000006'
        row = {
            'property': {'property_id': property_id, 'issuer_id': issuer_id},
            'issuance': {'schema_version': 1, 'property_id': property_id, 'issuer_id': issuer_id,
                         'approved_supply': 100, 'cumulative_issued_supply': 10,
                         'remaining_issuance_capacity': 90},
            'issuer_balance': {'schema_version': 1, 'property_id': property_id,
                               'holder_id': issuer_id, 'quantity': 10},
            'issuance_operation': {
                'schema_version': 1, 'operation_id': '97000000-0000-4000-8000-000000000001',
                'authorizing_msp': 'Org1MSP', 'authorizing_principal': 'test-only-principal',
                'function': 'IssueANSH', 'request_digest': 'a' * 64,
                'property_id': property_id, 'issuer_id': issuer_id, 'quantity': 10,
                'original_transaction_id': 'transaction-1', 'result': {},
            },
        }
        u.issuance_records(row)

    def test_mismatched_policy_and_metadata_are_rejected(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        definition = dict(name='tokansh', version='1.3', sequence=4,
                          endorsement_plugin='escc', validation_plugin='vscc',
                          validation_parameter='d3Jvbmc=', collections={}, init_required=False)
        with self.assertRaises(u.Stop):
            u.expected_definition(definition, '1.3', 4)
        malformed = dict(contract='tokansh', schema_version=1,
                          functions=list(u.M4_FUNCTIONS) + ['Unexpected'],
                          supply_interpretation=u.ONE_TIME_SUPPLY)
        with self.assertRaises(u.Stop):
            u.info(malformed, 'target')

    def test_target_metadata_rejects_shape_order_and_policy_mismatches(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        valid = {
            'contract': 'tokansh',
            'schema_version': 1,
            'functions': list(u.TRANSFER_FUNCTIONS),
            'supply_interpretation': u.ONE_TIME_SUPPLY,
        }
        invalid = []
        invalid.append({**valid, 'contract': 'basic'})
        invalid.append({**valid, 'schema_version': 2})
        invalid.append({**valid, 'functions': list(u.TRANSFER_FUNCTIONS[:-1])})
        invalid.append({**valid, 'functions': list(u.TRANSFER_FUNCTIONS) + ['Unexpected']})
        reordered = list(u.TRANSFER_FUNCTIONS)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        invalid.append({**valid, 'functions': reordered})
        invalid.append({**valid, 'supply_interpretation': 'UNSUPPORTED'})
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(u.Stop):
                u.info(candidate, 'target')

    def test_schema_version_requires_exact_integer_type(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        valid = {
            'contract': 'tokansh',
            'schema_version': 1,
            'functions': list(u.TRANSFER_FUNCTIONS),
            'supply_interpretation': u.ONE_TIME_SUPPLY,
        }
        u.info(valid, 'target')
        for schema_version in (True, 1.0, '1'):
            candidate = {**valid, 'schema_version': schema_version}
            with self.subTest(schema_version=repr(schema_version)), self.assertRaisesRegex(u.Stop, 'schema_version'):
                u.info(candidate, 'target')

    def test_structured_historical_report_binds_and_preserves_snapshot(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference = structured_snapshot(u)
            report_path, snapshot_path = write_verified_evidence(u, directory, reference)
            report, loaded = u.historical_verification(
                report_path, u.digest(report_path), snapshot_path, u.digest(snapshot_path))
            actual = copy.deepcopy(reference)
            actual['deployment_id'] = 'current-preflight'
            for row in actual['organizations'].values():
                row['approval_previous'] = fixtures.approved('tokansh_1.2:' + 'e' * 64, '1.2', 3)
                row['channel']['height'] += 1
                row['channel']['previousBlockHash'] = row['channel']['currentBlockHash']
                row['channel']['currentBlockHash'] = base64.b64encode(b'Y' * 32).decode()
            u.snapshot(loaded, loaded['deployment_id'], '1.1', 2)
            u.snapshot(actual, actual['deployment_id'])
            u.preserve_historical(loaded, actual, report)

    def test_structured_report_digest_and_binding_fail_closed(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference = structured_snapshot(u)
            report_path, snapshot_path = write_verified_evidence(u, directory, reference)
            with self.assertRaisesRegex(u.Stop, 'report hash'):
                u.historical_verification(report_path, '0' * 64, snapshot_path, u.digest(snapshot_path))
            report = json.loads(report_path.read_text())
            report['version'] = '1.1'
            report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(u.Stop, 'not bound'):
                u.historical_verification(report_path, u.digest(report_path), snapshot_path, u.digest(snapshot_path))

    def test_unreconciled_historical_issuer_balance_change_stops(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference = structured_snapshot(u)
            report_path, snapshot_path = write_verified_evidence(u, directory, reference)
            report, loaded = u.historical_verification(
                report_path, u.digest(report_path), snapshot_path, u.digest(snapshot_path))
            actual = copy.deepcopy(loaded)
            actual['deployment_id'] = 'current-preflight'
            for row in actual['organizations'].values():
                row['approval_previous'] = fixtures.approved('tokansh_1.2:' + 'e' * 64, '1.2', 3)
                row['issuer_balance']['quantity'] = 2
            with self.assertRaisesRegex(u.Stop, 'reconciliation evidence'):
                u.preserve_historical(loaded, actual, report)

    def _reconciled_case(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        directory = Path(tempfile.mkdtemp(prefix='reconciliation-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(directory, ignore_errors=True))
        reference = structured_snapshot(u)
        report_path, snapshot_path = write_verified_evidence(u, directory, reference)
        report, loaded = u.historical_verification(
            report_path, u.digest(report_path), snapshot_path, u.digest(snapshot_path))
        actual = copy.deepcopy(loaded)
        actual['deployment_id'] = 'current-preflight'
        for row in actual['organizations'].values():
            row['approval_previous'] = fixtures.approved('tokansh_1.2:' + 'e' * 64, '1.2', 3)
            row['issuer_balance']['quantity'] = 2
            row['channel']['height'] += 3
            row['channel']['previousBlockHash'] = row['channel']['currentBlockHash']
            row['channel']['currentBlockHash'] = base64.b64encode(b'R' * 32).decode()
        reconciliation_path = write_transfer_reconciliation(
            u, directory, loaded, actual, report, snapshot_path)
        return u, directory, loaded, actual, report, reconciliation_path

    def test_transfer_reconciliation_validates_both_orgs_and_preserves_balances(self):
        u, _, reference, actual, report, path = self._reconciled_case()
        reconciliation = u.transfer_reconciliation(
            path, u.digest(path), reference, actual, report, u.digest(path.parent / 'historical-snapshot.json'))
        u.preserve_historical(reference, actual, report, reconciliation)
        self.assertEqual(reconciliation['final_balances'][reference['organizations']['1']['issuer_balance']['holder_id']], 2)

    def test_transfer_reconciliation_rejects_tampered_or_incomplete_evidence(self):
        u, directory, reference, actual, report, path = self._reconciled_case()
        value = json.loads(path.read_text())
        evidence_path = directory / 'transfer-evidence' / 'org2.json'
        evidence = json.loads(evidence_path.read_text())
        evidence['final_balances'][reference['organizations']['1']['issuer_balance']['holder_id']] = 3
        evidence_path.write_text(json.dumps(evidence))
        value['evidence_sha256']['org2.json'] = u.digest(evidence_path)
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(u.Stop, 'evidence content'):
            u.transfer_reconciliation(
                path, u.digest(path), reference, actual, report,
                u.digest(directory / 'historical-snapshot.json'))

        u, directory, reference, actual, report, path = self._reconciled_case()
        value = json.loads(path.read_text())
        value['organizations'].pop('2')
        path.write_text(json.dumps(value))
        with self.assertRaises((u.Stop, KeyError)):
            u.transfer_reconciliation(
                path, u.digest(path), reference, actual, report,
                u.digest(directory / 'historical-snapshot.json'))

    def test_transfer_reconciliation_rejects_conflicting_history_and_digest(self):
        u, directory, reference, actual, report, path = self._reconciled_case()
        value = json.loads(path.read_text())
        value['transfers'][1]['command']['quantity'] = 3
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(u.Stop, 'final balances'):
            u.transfer_reconciliation(
                path, u.digest(path), reference, actual, report,
                u.digest(directory / 'historical-snapshot.json'))

        with self.assertRaisesRegex(u.Stop, 'reconciliation hash'):
            u.transfer_reconciliation(
                path, '0' * 64, reference, actual, report,
                u.digest(directory / 'historical-snapshot.json'))

    def test_main_preflight_consumes_structured_baseline_without_flat_keys(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / 'release'; release.mkdir(mode=0o700)
            network = root / 'network'; network.mkdir(mode=0o700)
            evidence = root / 'historical'; evidence.mkdir(mode=0o700)
            reference = structured_snapshot(u)
            report_path, snapshot_path = write_verified_evidence(u, evidence, reference)
            actual = copy.deepcopy(reference)
            actual['deployment_id'] = 'current-preflight'
            for row in actual['organizations'].values():
                row['approval_previous'] = fixtures.approved('tokansh_1.2:' + 'e' * 64, '1.2', 3)
                row['channel']['height'] += 1
                row['channel']['previousBlockHash'] = row['channel']['currentBlockHash']
                row['channel']['currentBlockHash'] = base64.b64encode(b'Z' * 32).decode()

            class ReadOnlyRunner:
                def __init__(self):
                    self.evidence = evidence

                def capture(self, deployment_id, property_id, operation_id):
                    return copy.deepcopy(actual)

            args = [
                'preflight', '--authorize-preflight', '--deployment-id', actual['deployment_id'],
                '--network-root', str(network), '--release-directory', str(release),
                '--property-id', reference['property_id'], '--operation-id', reference['operation_id'],
                '--preservation-baseline', str(snapshot_path),
                '--preservation-sha256', u.digest(snapshot_path),
                '--historical-verification-report', str(report_path),
                '--historical-verification-sha256', u.digest(report_path),
            ]
            with patch.object(u, 'Runner', return_value=ReadOnlyRunner()):
                u.main(args)
            self.assertTrue((release / 'baseline.json').exists())

    def test_main_preflight_accepts_explicit_fresh_current_baseline(self):
        u = workflow()
        u.configure_next_transition('1.2', 3, '1.3', 4)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            release = root / 'release'; release.mkdir(mode=0o700)
            network = root / 'network'; network.mkdir(mode=0o700)
            current = structured_snapshot(u, 'fresh-current')
            for row in current['organizations'].values():
                row['approval_previous'] = fixtures.approved('tokansh_1.2:' + 'e' * 64, '1.2', 3)

            class ReadOnlyRunner:
                def __init__(self):
                    self.evidence = release

                def capture(self, deployment_id, property_id, operation_id):
                    observed = copy.deepcopy(current)
                    observed['deployment_id'] = deployment_id
                    return observed

            args = [
                'preflight', '--authorize-preflight', '--deployment-id', 'fresh-current',
                '--network-root', str(network), '--release-directory', str(release),
                '--property-id', current['property_id'], '--operation-id', current['operation_id'],
                '--accept-fresh-current-baseline',
            ]
            with patch.object(u, 'Runner', return_value=ReadOnlyRunner()):
                u.main(args)
            provenance = u.checks.load(release / 'baseline-provenance.json')
            self.assertEqual(provenance['kind'], 'NEWLY_OBSERVED_MVP_CURRENT_BASELINE')
            self.assertEqual(u.checks.load(release / 'baseline.json')['deployment_id'], 'fresh-current')


if __name__ == '__main__':
    unittest.main()
