"""Mocked wireless ADB route checks; never contacts a headset."""

import argparse
import contextlib
import importlib.util
import io
import subprocess
import unittest
from pathlib import Path
from unittest.mock import call, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "Tools/keep_processing_connection.py"
SPEC = importlib.util.spec_from_file_location("processing_route", MODULE_PATH)
route = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(route)

SERIAL = "192.0.2.10:5555"
ADB = "/tools/android sdk/adb"
MAPPING = "host-serial tcp:8443 tcp:8443\n"


def completed(stdout=""):
    return subprocess.CompletedProcess([], 0, stdout, "")


def failed():
    return subprocess.CalledProcessError(1, [ADB], stderr="device offline")


class RouteChecks(unittest.TestCase):
    def run_route(self, responses):
        with patch.object(route.subprocess, "run", side_effect=responses) as run:
            route.ensure_route(ADB, SERIAL)
        for invocation in run.call_args_list:
            self.assertEqual(invocation.kwargs, {
                "capture_output": True, "text": True, "check": True, "timeout": 8,
            })
        return [invocation.args[0] for invocation in run.call_args_list]

    def test_healthy_route_does_not_change_connection_or_mapping(self):
        commands = self.run_route([completed("device\n"), completed(MAPPING)])
        self.assertEqual(commands, [
            [ADB, "-s", SERIAL, "get-state"],
            [ADB, "-s", SERIAL, "reverse", "--list"],
        ])

    def test_missing_mapping_is_restored_and_verified(self):
        commands = self.run_route([
            completed("device"), completed(""), completed(), completed(MAPPING),
        ])
        self.assertEqual(commands[-2:], [
            [ADB, "-s", SERIAL, "reverse", "tcp:8443", "tcp:8443"],
            [ADB, "-s", SERIAL, "reverse", "--list"],
        ])

    def test_disconnected_device_is_reconnected_before_restoring_mapping(self):
        commands = self.run_route([
            failed(), completed("connected"), completed("device"),
            completed(""), completed(), completed(MAPPING),
        ])
        self.assertEqual(commands[1:3], [
            [ADB, "connect", SERIAL], [ADB, "-s", SERIAL, "get-state"],
        ])
        self.assertIn([ADB, "-s", SERIAL, "reverse", "tcp:8443", "tcp:8443"], commands)

    def test_offline_state_reconnects_even_when_get_state_exits_zero(self):
        commands = self.run_route([
            completed("offline"), completed(), completed("device"), completed(MAPPING),
        ])
        self.assertEqual(commands[1], [ADB, "connect", SERIAL])

    def test_wrong_destination_is_replaced_without_removing_other_routes(self):
        commands = self.run_route([
            completed("device"),
            completed("host-serial tcp:8443 tcp:9999\nhost-serial tcp:9000 tcp:9000\n"),
            completed(), completed(MAPPING + "host-serial tcp:9000 tcp:9000\n"),
        ])
        self.assertEqual(commands[2], [ADB, "-s", SERIAL, "reverse", "tcp:8443", "tcp:8443"])
        self.assertEqual(len(commands), 4)

    def test_failed_connect_does_not_claim_route_ready(self):
        for result in (failed(), completed("offline")):
            with self.subTest(result=result), patch.object(route.subprocess, "run", side_effect=[
                failed(), completed("failed to connect"), result,
            ]), self.assertRaises(route.RouteError):
                route.ensure_route(ADB, SERIAL)

    def test_failed_mapping_verification_is_reported(self):
        with patch.object(route.subprocess, "run", side_effect=[
            completed("device"), completed(), completed(), completed(),
        ]), self.assertRaisesRegex(route.RouteError, "mapping"):
            route.ensure_route(ADB, SERIAL)

    def test_command_failures_and_timeouts_are_reported(self):
        for error in (failed(), subprocess.TimeoutExpired([ADB], 8)):
            with self.subTest(error=error), patch.object(route.subprocess, "run", side_effect=[
                completed("device"), error,
            ]), self.assertRaises(route.RouteError):
                route.ensure_route(ADB, SERIAL)

    def test_similarly_named_ports_are_not_accepted(self):
        commands = self.run_route([
            completed("device"), completed("host-serial tcp:84430 tcp:8443\n"),
            completed(), completed(MAPPING),
        ])
        self.assertEqual(commands[2][-2:], ["tcp:8443", "tcp:8443"])


class CliChecks(unittest.TestCase):
    def test_explicit_ip_and_port_validation(self):
        for value in (SERIAL, "192.0.2.10:1", "192.0.2.10:65535", "[2001:db8::1]:5555"):
            with self.subTest(value=value):
                self.assertEqual(route.wireless_serial(value), value)
        for value in (None, 5, "", "emulator-5554", "host:5555", "192.0.2.10:0",
                      "192.0.2.10:65536", "192.0.2.10:５５５５", "192.0.2.10:5555;echo x",
                      "2001:db8::1:5555", "192.0.2.10:5555\n"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                route.wireless_serial(value)

    def test_once_succeeds_without_sleep_and_passes_selected_executable(self):
        with (
            patch.object(route, "ensure_route") as ensure,
            patch.object(route.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = route.main(["--serial", SERIAL, "--adb", ADB, "--once"])
        self.assertEqual(result, 0)
        ensure.assert_called_once_with(ADB, SERIAL)
        sleep.assert_not_called()
        self.assertIn("ready", output.getvalue())

    def test_once_failure_returns_nonzero_with_actionable_status(self):
        with (
            patch.object(route, "ensure_route", side_effect=route.RouteError("Check headset Wi-Fi")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = route.main(["--serial", SERIAL, "--once"])
        self.assertEqual(result, 1)
        self.assertIn("Check headset Wi-Fi", output.getvalue())

    def test_missing_adb_exits_with_install_or_path_instructions(self):
        with (
            patch.object(route.subprocess, "run", side_effect=FileNotFoundError()),
            contextlib.redirect_stderr(io.StringIO()) as output,
        ):
            result = route.main(["--serial", SERIAL])
        self.assertEqual(result, 2)
        self.assertIn("--adb", output.getvalue())
        self.assertIn("Android SDK Platform-Tools", output.getvalue())

    def test_loop_retries_failure_and_logs_only_state_transitions(self):
        error = route.RouteError("Check headset Wi-Fi")
        with (
            patch.object(route, "ensure_route", side_effect=[error, error, None, None]) as ensure,
            patch.object(route.time, "sleep", side_effect=[None, None, None, KeyboardInterrupt]) as sleep,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = route.main(["--serial", SERIAL])
        self.assertEqual(result, 0)
        self.assertEqual(ensure.call_count, 4)
        self.assertEqual(sleep.call_args_list, [call(5)] * 4)
        self.assertEqual(output.getvalue().count("Check headset Wi-Fi"), 1)
        self.assertEqual(output.getvalue().count("ready"), 1)

    def test_ctrl_c_during_adb_command_exits_cleanly(self):
        with (
            patch.object(route.subprocess, "run", side_effect=KeyboardInterrupt),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(route.main(["--serial", SERIAL]), 0)


if __name__ == "__main__":
    unittest.main()
