"""Focused tests for later explicit TokANSH lifecycle transitions."""
import copy
import importlib.util
from pathlib import Path
import unittest


def workflow():
    spec = importlib.util.spec_from_file_location(
        'upgrade_transition_workflow', Path(__file__).with_name('upgrade-workflow.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


if __name__ == '__main__':
    unittest.main()
