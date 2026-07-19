#!/usr/bin/env python3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import tickstone_ble_connection  # noqa: E402


class BluetoothConnectionDefaultsTest(unittest.TestCase):
    def test_configures_every_hci_adapter_with_six_second_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controls = []
            for adapter in ("hci0", "hci1"):
                control = root / adapter / "supervision_timeout"
                control.parent.mkdir()
                control.write_text("42\n", encoding="ascii")
                controls.append(control)

            configured = tickstone_ble_connection.configure(root)

            self.assertEqual(configured, controls)
            self.assertEqual(tickstone_ble_connection.SUPERVISION_TIMEOUT_UNITS, 600)
            self.assertTrue(all(control.read_text(encoding="ascii") == "600\n" for control in controls))

    def test_missing_kernel_control_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(RuntimeError, "supervision_timeout"):
                tickstone_ble_connection.configure(Path(directory))


class SystemdContractTest(unittest.TestCase):
    def test_connection_defaults_are_required_before_the_receiver(self):
        sync_unit = (ROOT / "deploy" / "tickstone-sync.service").read_text(encoding="utf-8")
        defaults_unit = (ROOT / "deploy" / "tickstone-ble-connection.service").read_text(encoding="utf-8")

        self.assertIn("Requires=bluetooth.service tickstone-ble-connection.service", sync_unit)
        self.assertIn("After=bluetooth.service tickstone-ble-connection.service", sync_unit)
        self.assertIn("Before=tickstone-sync.service", defaults_unit)
        self.assertIn("ExecStart=/usr/bin/python3 /usr/local/libexec/tickstone-ble-connection", defaults_unit)
        self.assertIn("ReadWritePaths=/sys/kernel/debug/bluetooth", defaults_unit)
        self.assertNotIn("ProtectKernelTunables=true", defaults_unit)

    def test_deploy_contract_has_exactly_one_canonical_receiver(self):
        receiver_commands = []
        for unit_path in (ROOT / "deploy").glob("*.service"):
            for line in unit_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ExecStart=") and "tickstone_ble_sync.py" in line and "--watch" in line:
                    receiver_commands.append((unit_path.name, line))

        self.assertEqual(len(receiver_commands), 1)
        self.assertEqual(receiver_commands[0][0], "tickstone-sync.service")


if __name__ == "__main__":
    unittest.main()
