"""AppImage integration boundaries, without a physical phone or real library."""
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from musicsync import APP_ID, runtime
from musicsync.backend.replaygain import command
from musicsync.backend.status import StatusService
from musicsync.backend.worker import execute
from musicsync.backend.workflow import helper
from musicsync.models import Command, Result
from musicsync.settings import Settings
from test_process import APP, run


class AppImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='musicsync-bundle-')
        self.root = Path(self.tmp.name) / 'AppDir Ω $cash ; literal'
        marker = self.root / 'usr/share/musicsync' / APP_ID
        marker.parent.mkdir(parents=True)
        marker.write_text(APP_ID)
        self.env = patch.dict(os.environ, {'APPDIR': str(self.root)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_private_tools_do_not_fall_back_to_path(self):
        for name in runtime.PRIVATE_TOOLS:
            with self.subTest(name=name):
                self.assertEqual(runtime.tool_program(name), str(self.root / 'usr/libexec/musicsync' / name))
                with self.assertRaises(OSError):
                    runtime.executable(name)

    def test_qprocess_uses_private_executable_even_with_host_tool_present(self):
        target = self.root / 'usr/libexec/musicsync/rsync'
        target.parent.mkdir(parents=True)
        target.write_text(f'#!{sys.executable}\nimport sys; print("PRIVATE",repr(sys.argv[1:]))\n')
        target.chmod(0o755)
        result, _ = run(Command('rsync', ['space $literal; Ω']))
        self.assertEqual(result.code, 0, result.stderr)
        self.assertIn("PRIVATE ['space $literal; Ω']", result.stdout)

    def test_host_tools_remain_on_host(self):
        for name in runtime.HOST_TOOLS:
            self.assertEqual(runtime.tool_program(name), name)

    def test_source_and_unrelated_appdir_use_host_defaults(self):
        (self.root / 'usr/share/musicsync' / APP_ID).unlink()
        self.assertIsNone(runtime.appdir())
        self.assertEqual(runtime.tool_program('rsync'), 'rsync')
        self.assertEqual(runtime.effective_preset(runtime.SYSTEM_PRESET), runtime.SYSTEM_PRESET)
        program, args = runtime.worker_invocation('{}')
        self.assertEqual((program, args), (sys.executable, ['-m', 'musicsync.backend.worker', '{}']))

    def test_preset_relative_resolution_preserves_custom_and_serialized_default(self):
        settings = Settings()
        self.assertEqual(settings.preset, runtime.SYSTEM_PRESET)
        expected = str(self.root / 'usr/share/musicsync/presets/no_album.ini')
        self.assertEqual(command(settings).args[5], expected)
        self.assertEqual(runtime.effective_preset('/tmp/custom Ω.ini'), '/tmp/custom Ω.ini')
        self.assertEqual(settings.preset, runtime.SYSTEM_PRESET)

    def test_frozen_worker_uses_kernel_executable_not_python_or_cwd(self):
        binary = self.root / 'usr/lib/musicsync/musicsync.bin'
        with patch.dict(runtime.__dict__, {'__compiled__': object()}), patch('os.readlink', return_value=str(binary)):
            self.assertEqual(runtime.compiled_directory(), binary.parent)
            self.assertEqual(runtime.worker_invocation('payload Ω'), (str(binary), ['--musicsync-worker', 'payload Ω']))
            os.environ.pop('APPDIR')
            self.assertEqual(runtime.appdir(), self.root)

    def test_missing_host_dependency_stops_startup_before_scan_or_mount(self):
        service = StatusService()
        generator = service._read(Settings(), scan=True)
        first = next(generator)
        self.assertEqual(json.loads(first.args[-1])['programs'], list(runtime.HOST_TOOLS))
        with self.assertRaises(StopIteration) as done:
            generator.send(Result(1, stderr='Missing runtime tools: kdeconnect-cli, sshfs'))
        self.assertEqual(done.exception.value['device_status'], 'Host setup incomplete')
        self.assertIn('sshfs', done.exception.value['filesystem'])
        service.deleteLater()

    def test_dependency_helper_reports_host_setup_and_missing_private_tools(self):
        with patch('musicsync.backend.worker.shutil.which', return_value=None):
            with self.assertRaisesRegex(OSError, 'host KDE Connect and SSHFS/FUSE'):
                execute({'action': 'dependencies', 'programs': ['kdeconnect-cli', 'sshfs']})
            with self.assertRaisesRegex(OSError, 'rsync'):
                execute({'action': 'dependencies', 'programs': ['rsync']})

    def test_host_environment_restored_without_changing_parent(self):
        with patch.dict(os.environ, {'MUSICSYNC_HOST_ENV_SAVED': '1',
                         'MUSICSYNC_HOST_LD_LIBRARY_PATH': '/original/libs',
                         'LD_LIBRARY_PATH': '/private/libs', 'QT_PLUGIN_PATH': '/private/plugins'}):
            os.environ.pop('MUSICSYNC_HOST_QT_PLUGIN_PATH', None)
            env = runtime.host_environment()
            self.assertEqual(env['LD_LIBRARY_PATH'], '/original/libs')
            self.assertNotIn('QT_PLUGIN_PATH', env)
            self.assertEqual(os.environ['LD_LIBRARY_PATH'], '/private/libs')

    def test_worker_payload_is_an_argument_not_shell_interpolation(self):
        command = helper('source', 'test', source='/tmp/$(touch nope); Ω "quote"')
        self.assertEqual(json.loads(command.args[-1])['source'], '/tmp/$(touch nope); Ω "quote"')

    def test_build_configuration_is_standalone_and_metadata_consistent(self):
        root = Path(__file__).resolve().parents[1]
        spec = (root / 'packaging/appimage/pysidedeploy.spec').read_text()
        self.assertIn('mode = standalone', spec)
        self.assertNotIn('onefile', spec)
        self.assertNotIn(str(Path.home()), spec)
        desktop = (root / 'resources' / f'{APP_ID}.desktop').read_text()
        self.assertIn('Utility;', desktop)
        pins = json.loads((root / 'packaging/appimage/tools.json').read_text())
        for item in pins.values():
            self.assertEqual(len(item['sha256']), 64)

    @unittest.skipUnless(shutil.which('gcc'), 'native launcher test requires a C compiler')
    def test_native_launcher_preserves_appearance_and_external_xdg(self):
        source = Path(__file__).resolve().parents[1] / 'packaging/appimage/AppRun.c'
        launcher = self.root / 'AppRun'
        subprocess.run(['gcc', '-o', str(launcher), str(source)], check=True, capture_output=True)
        child = self.root / 'usr/lib/musicsync/musicsync.bin'
        child.parent.mkdir(parents=True)
        child.write_text(f'#!{sys.executable}\nimport os,json; print(json.dumps(dict(os.environ)))\n')
        child.chmod(0o755)
        preserved = {'QT_QPA_PLATFORMTHEME': 'qt6ct', 'QT_QPA_PLATFORM': 'wayland;xcb',
                     'QT_STYLE_OVERRIDE': '', 'QT_ICON_THEME': 'ExampleIcons',
                     'GTK_THEME': 'ExternalTestTheme', 'GSETTINGS_BACKEND': 'memory',
                     'XDG_CONFIG_HOME': str(self.root / 'external config Ω')}
        result = subprocess.run([str(launcher)], env=dict(os.environ, **preserved),
                                check=True, capture_output=True, text=True)
        environment = json.loads(result.stdout)
        for key, value in preserved.items():
            self.assertEqual(environment[key], value)
        self.assertNotIn('QT_PLUGIN_PATH', environment)
        self.assertEqual(environment['GIO_MODULE_DIR'], str(self.root / 'usr/lib/musicsync/gio/modules'))
        self.assertEqual(environment['GSETTINGS_SCHEMA_DIR'], str(self.root / 'usr/share/musicsync/gtk-schemas'))

    def test_host_gsettings_environment_is_restored(self):
        original = {'GIO_MODULE_DIR': '/external/gio', 'GIO_EXTRA_MODULES': '/external/extra',
                    'GSETTINGS_SCHEMA_DIR': '/external/schemas'}
        environment = {'MUSICSYNC_HOST_ENV_SAVED': '1'}
        for name, value in original.items():
            environment[name] = '/private'
            environment['MUSICSYNC_HOST_' + name] = value
        with patch.dict(os.environ, environment):
            restored = runtime.host_environment()
            for name, value in original.items():
                self.assertEqual(restored[name], value)

    def test_theme_build_pins_exact_sdk_and_keeps_required_kde_sources(self):
        root = Path(__file__).resolve().parents[1]
        pins = json.loads((root / 'packaging/appimage/theme-inputs.json').read_text())
        for name, item in pins.items():
            self.assertEqual(len(item['sha256']), 64)
            self.assertTrue(item['url'].startswith('https://'))
            self.assertNotIn('trialuser02', item['url'])
            if name.endswith('.7z'):
                self.assertIn('/qt6_6112/', item['url'])
        self.assertIn('qt6ct-kde.patch', pins)
        for module in ('kcolorscheme', 'kiconthemes', 'kconfig', 'breeze-icons'):
            self.assertIn(module + '-6.29.0.tar.xz', pins)
