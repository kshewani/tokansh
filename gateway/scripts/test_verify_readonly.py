"""Verifier-only tests; never contact a network or read real credentials."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from verify_readonly import peer_cli, sanitized_stderr


class VerifierTests(unittest.TestCase):
    def test_each_command_has_explicit_peer_without_mutating_environment(self):
        env = {"CORE_PEER_ADDRESS": "inherited:9999"}
        with patch("verify_readonly.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as run:
            for address, operation in [("custom-cp:7061", "channel"), ("custom-lp:7051", "chaincode"), ("custom-cp:7061", "channel")]:
                self.assertEqual(peer_cli(Path('/test'), env, address, operation), "ok")
                self.assertEqual(run.call_args.kwargs['env']['CORE_PEER_ADDRESS'], address)
        self.assertEqual(env, {"CORE_PEER_ADDRESS": "inherited:9999"})

    def test_failure_preserves_useful_error_but_redacts_material(self):
        stderr = 'chaincode is not installed\n-----BEGIN PRIVATE KEY-----\nsensitive\n-----END PRIVATE KEY-----\ntoken=hidden'
        with patch("verify_readonly.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", stderr)):
            with self.assertRaisesRegex(RuntimeError, 'chaincode is not installed') as error:
                peer_cli(Path('/test'), {}, 'lp:7051', 'chaincode')
        self.assertNotIn('sensitive', str(error.exception))
        self.assertNotIn('hidden', str(error.exception))

    def test_timeout_stderr_is_sanitized_without_retry(self):
        with patch('verify_readonly.subprocess.run', side_effect=subprocess.TimeoutExpired('peer', 20, stderr=b'token=hidden')) as run:
            with self.assertRaisesRegex(RuntimeError, 'timed out') as error:
                peer_cli(Path('/test'), {}, 'cp:7061', 'channel')
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('hidden', str(error.exception))

    def test_redaction_is_bounded_and_handles_incomplete_pem(self):
        self.assertNotIn('sensitive', sanitized_stderr('-----BEGIN PRIVATE KEY-----\nsensitive', {}))
        self.assertNotIn('value123', sanitized_stderr('error value123', {'ACCESS_TOKEN': 'value123'}))
        self.assertLessEqual(len(sanitized_stderr('x ' * 3000, {})), 2000)


if __name__ == '__main__':
    unittest.main()
