import io
import json
import subprocess
import unittest
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import health
import supervisor
sys.path.insert(0, str(Path(__file__).parent / 'setup'))
import verify_bookworm

class PackageTests(unittest.TestCase):
    def test_shipped_bundle_requires_fixed_quoting_and_rejects_old_expression(self):
        verify_bookworm.verify('bundle;' + verify_bookworm.FIXED + ';bundle')
        for body in (verify_bookworm.OLD, '', verify_bookworm.FIXED + verify_bookworm.OLD):
            with self.assertRaises(ValueError): verify_bookworm.verify(body)

class HealthTests(unittest.TestCase):
    def check(self, body, status=200):
        response = Mock(status=status)
        response.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch('urllib.request.build_opener', return_value=opener):
            result = health.healthy('/cp-opti')
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 5)
        return result

    def test_only_valid_manifests_pass(self):
        self.assertTrue(self.check(b'{"shell":{},"system":{}}'))
        for body in (b'<html>Sign in</html>', b'{}', b'[]', b'{"shell":{},"system":[]}', b'x' * (1024*1024+1)):
            self.assertFalse(self.check(body))
        self.assertFalse(self.check(b'{"shell":{},"system":{}}', 302))

    def test_unreachable_and_redirects_fail(self):
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = OSError('offline')
            self.assertFalse(health.healthy('/cp-opti'))
        self.assertIsNone(health.NoRedirect().redirect_request(None, None, None, None, None, None))

class SupervisorTests(unittest.TestCase):
    def test_configuration_rejects_unknown_target_origins_and_missing_keys(self):
        valid = {'TARGET': 'ptm@192.168.1.11', 'URL_ROOT': '/cp-opti', 'ORIGINS': 'https://webapp.lan:8444'}
        for changes in ({'TARGET': 'ptm@evil'}, {'URL_ROOT': '/cp-other'},
                        {'ORIGINS': 'https://webapp.lan:8444.evil.example'}, {'ORIGINS': ''}):
            with patch.dict(supervisor.os.environ, {**valid, **changes}, clear=True):
                with self.assertRaises(ValueError): supervisor.configuration()
        file = MagicMock()
        file.is_file.return_value = False
        with patch.dict(supervisor.os.environ, valid, clear=True), patch.object(supervisor, 'Path', return_value=file):
            with self.assertRaisesRegex(ValueError, 'missing'): supervisor.configuration()
        file.is_file.return_value = True
        with patch.dict(supervisor.os.environ, valid, clear=True), patch.object(supervisor, 'Path', return_value=file):
            self.assertEqual(supervisor.configuration(), (valid['TARGET'], valid['URL_ROOT']))
            self.assertIn('UrlRoot = /cp-opti', file.__truediv__.return_value.write_text.call_args.args[0])

    def simulate(self, scenario):
        children = [Mock(stdin=io.BytesIO(), stdout=io.BytesIO()), Mock()]
        for child in children:
            child.poll.return_value = None
        clock = [0]
        handlers = {}
        def register(sig, fn): handlers[sig] = fn
        def tick(_):
            clock[0] += 16
            if scenario == 'signal' or clock[0] > 64:
                handlers[supervisor.signal.SIGTERM](None, None)
        if scenario == 'ssh': children[0].poll.side_effect = [1, 1]
        if scenario == 'ws': children[1].poll.side_effect = [1, 1]
        if scenario == 'kill':
            children[0].wait.side_effect = [subprocess.TimeoutExpired('ssh', 5), 0]
        healthy = Mock(return_value=scenario not in ('health', 'kill'))
        popen = Mock(side_effect=children if scenario != 'spawn' else [children[0], OSError('ws failed')])
        with patch.object(supervisor, 'configuration', return_value=('ptm@192.168.1.11', '/cp-opti')), \
             patch.object(supervisor.subprocess, 'Popen', popen), \
             patch.object(supervisor.signal, 'signal', register), \
             patch.object(supervisor.time, 'monotonic', lambda: clock[0]), \
             patch.object(supervisor.time, 'sleep', tick), \
             patch.object(supervisor, 'healthy', healthy):
            if scenario == 'spawn':
                with self.assertRaises(OSError): supervisor.run()
                result = None
            else: result = supervisor.run()
        return result, children, healthy

    def test_either_process_exit_requests_restart_and_cleans_peer(self):
        for scenario, peer in (('ssh', 1), ('ws', 0)):
            result, children, _ = self.simulate(scenario)
            self.assertEqual(result, 1)
            children[peer].terminate.assert_called_once()
            for child in children: child.wait.assert_called()

    def test_two_failed_checks_restart(self):
        result, children, healthy = self.simulate('health')
        self.assertEqual(result, 1)
        self.assertEqual(healthy.call_count, 2)
        for child in children: child.terminate.assert_called_once()

    def test_signal_cleanup_exits_successfully(self):
        result, children, _ = self.simulate('signal')
        self.assertEqual(result, 0)
        for child in children: child.terminate.assert_called_once()

    def test_stuck_child_is_killed_and_failed_launch_cleans_ssh(self):
        _, children, _ = self.simulate('kill')
        children[0].kill.assert_called_once()
        _, children, _ = self.simulate('spawn')
        children[0].terminate.assert_called_once()

if __name__ == '__main__': unittest.main()
