import io
import tempfile
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
import bridge_compat

class BridgeCompatibilityTests(unittest.TestCase):
    def bus_type(self, fail='connect'):
        class Bus:
            _default_system_instance = None
            _default_user_instance = None
            calls = 0
            @staticmethod
            def default_user(attach_event=True):
                if Bus._default_user_instance is None:
                    Bus._default_user_instance = Mock(value=None)
                    Bus.calls += 1
                    if fail == 'connect': raise OSError(123, 'No medium found')
                    Bus._default_user_instance.value = 1234
                    if fail == 'attach' and attach_event: raise OSError(22, 'attach failed')
                return Bus._default_user_instance
            @staticmethod
            def default_system(attach_event=True):
                if Bus._default_system_instance is None:
                    Bus._default_system_instance = Mock(value=5678)
                    Bus.calls += 1
                return Bus._default_system_instance
        return Bus

    def test_failed_creation_never_poisons_cache_and_preserves_original_error(self):
        for failure, code in (('connect', 123), ('attach', 22)):
            bus = self.bus_type(failure)
            bridge_compat.install_bus_retry(bus)
            for _ in range(3):
                with self.assertRaises(OSError) as error: bus.default_user()
                self.assertEqual(error.exception.errno, code)
                self.assertIsNone(bus._default_user_instance)
            self.assertEqual(bus.calls, 3)
            self.assertEqual(bus.default_system().value, 5678)

    def test_healthy_bus_is_reused_and_options_are_preserved(self):
        bus = self.bus_type('attach')
        bridge_compat.install_bus_retry(bus)
        instance = bus.default_user(attach_event=False)
        self.assertIs(bus.default_user(), instance)
        self.assertIs(bus.default_system(), bus.default_system())
        self.assertEqual(bus.calls, 2)

    def test_existing_bus_error_does_not_discard_a_shared_connection(self):
        bus = self.bus_type()
        instance = Mock(value=1234)
        bus._default_user_instance = instance
        bus.default_user = staticmethod(Mock(side_effect=OSError(16, 'busy')))
        bridge_compat.install_bus_retry(bus)
        with self.assertRaises(OSError): bus.default_user()
        self.assertIs(bus._default_user_instance, instance)


class AuthorizationTests(unittest.TestCase):
    key = 'ssh-ed25519 ABC= pertal-cockpit'
    old = 'command="sudo -n /usr/bin/cockpit-bridge",restrict ' + key
    new = 'command="sudo -n /usr/local/libexec/pertal-cockpit-bridge",restrict ' + key

    def authorize(self, file):
        script = (Path(__file__).parent/'setup/authorize-key.sh').read_text()
        script = script.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
        return subprocess.run([sys.executable, '-c', script, str(file), self.key], capture_output=True)

    def test_exact_legacy_entry_migrates_and_unrelated_keys_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'authorized_keys'
            other = b'# untouched\r\nssh-ed25519 OTHER ordinary\r\n'
            file.write_bytes(other + self.old.encode() + b'\n')
            self.assertEqual(self.authorize(file).returncode, 0)
            self.assertEqual(file.read_bytes(), other + self.new.encode() + b'\n')
            self.assertEqual(self.authorize(file).returncode, 0)
            self.assertEqual(len(list(Path(directory).glob('*.before-*'))), 1)

    def test_conflicting_or_duplicate_entries_fail_without_changes(self):
        for body in (self.old+'\n'+self.old+'\n', self.key+'\n'):
            with tempfile.TemporaryDirectory() as directory:
                file = Path(directory)/'authorized_keys'
                file.write_bytes(body.encode())
                self.assertNotEqual(self.authorize(file).returncode, 0)
                self.assertEqual(file.read_bytes(), body.encode())
                self.assertFalse(list(Path(directory).glob('*.before-*')))

    def test_first_authorization_retains_existing_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory)/'authorized_keys'
            file.write_bytes(b'ssh-ed25519 OTHER ordinary')
            self.assertEqual(self.authorize(file).returncode, 0)
            self.assertEqual(file.read_bytes(), b'ssh-ed25519 OTHER ordinary\n'+self.new.encode()+b'\n')


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
