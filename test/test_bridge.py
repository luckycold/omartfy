from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ntfy_bridge as bridge_module
from ntfy_bridge import (
    Bridge,
    ConfigError,
    MediaError,
    atomic_json_write,
    authorization_header,
    normalize_server,
    public_server,
    stream_url,
    validate_config,
)
from mock_ntfy import MockNtfyServer, PNG


def wait_until(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class RunningServer:
    def __init__(self, token="", buffered_stream=False):
        self.server = MockNtfyServer(
            ("127.0.0.1", 0), "Test", token, buffered_stream=buffered_stream
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class BridgeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config_path = root / "config" / "omarchy" / "ntfy.json"
        self.state_dir = root / "state" / "omarchy" / "ntfy"
        self.output = io.StringIO()
        self.bridges = []

    def tearDown(self):
        for bridge in self.bridges:
            bridge.shutdown()
        self.temp.cleanup()

    def make_bridge(self, config=None):
        if config is not None:
            atomic_json_write(self.config_path, config)
        bridge = Bridge(self.config_path, self.state_dir, self.output)
        self.bridges.append(bridge)
        return bridge

    def events(self):
        return [json.loads(line) for line in self.output.getvalue().splitlines() if line]

    def test_config_validation_secret_preservation_and_atomic_modes(self):
        server = normalize_server({
            "label": "Home",
            "baseUrl": "https://example.com/proxy/",
            "topics": ["alerts", "backups"],
            "auth": {"type": "token", "secret": "secret-value"},
        })
        self.assertRegex(server["id"], r"^[0-9a-f]{12}$")
        self.assertEqual(server["baseUrl"], "https://example.com/proxy")
        edited = normalize_server({**server, "label": "Renamed", "auth": {"type": "token", "secret": ""}}, server)
        self.assertEqual(edited["auth"]["secret"], "secret-value")
        self.assertNotIn("secret-value", json.dumps(public_server(server)))

        with self.assertRaises(ConfigError):
            validate_config({"version": 1, "servers": [server, {**server, "id": "abcdefabcdef"}]})
        with self.assertRaises(ConfigError):
            normalize_server({"label": "Bad", "baseUrl": "http://example.com", "topics": ["a"],
                              "auth": {"type": "token", "secret": "x"}})
        with self.assertRaises(ConfigError):
            normalize_server({"label": "Bad", "baseUrl": "https://user@example.com", "topics": ["a"]})
        with self.assertRaises(ConfigError):
            normalize_server({"label": "Bad", "baseUrl": "https://example.com?q=1", "topics": ["a"]})
        with self.assertRaises(ConfigError):
            normalize_server({"label": "Bad", "baseUrl": "https://example.com", "topics": ["a", "a"]})

        atomic_json_write(self.config_path, {"version": 1, "servers": [server]})
        self.assertEqual(stat.S_IMODE(self.config_path.stat().st_mode), 0o600)

    def test_basic_bearer_headers_urls_and_no_secret_emission(self):
        basic = normalize_server({"label": "Basic", "baseUrl": "https://example.com/prefix",
                                  "topics": ["one", "two"], "auth": {"type": "basic", "username": "u", "secret": "p"}})
        token = normalize_server({"label": "Token", "baseUrl": "https://example.com",
                                  "topics": ["one"], "auth": {"type": "token", "secret": "top-secret"}})
        self.assertEqual(authorization_header(basic), "Basic dTpw")
        self.assertEqual(authorization_header(token), "Bearer top-secret")
        self.assertEqual(stream_url(basic, since="all"),
                         "https://example.com/prefix/one,two/json?since=all")
        bridge = self.make_bridge({"version": 1, "servers": [basic, token]})
        bridge.emit(bridge.snapshot())
        text = self.output.getvalue()
        self.assertNotIn("top-secret", text)
        self.assertNotIn('"secret":"p"', text)

    def test_sequence_update_clear_delete_cursor_and_bootstrap_dedupe(self):
        server = normalize_server({"label": "Home", "baseUrl": "https://example.com", "topics": ["alerts"]})
        bridge = self.make_bridge({"version": 1, "servers": [server]})
        first = {"event": "message", "id": "event-one", "time": 1, "topic": "alerts",
                 "sequence_id": "sequence", "message": "one"}
        bridge.apply_event(server["id"], first)
        key = f"{server['id']}:alerts:sequence"
        self.assertEqual(bridge.server_state(server["id"])["cursor"], "event-one")
        bridge.mark_read(server["id"])
        update = {"event": "message", "id": "event-two", "time": 2, "topic": "alerts",
                  "sequence_id": "sequence", "message": "two"}
        bridge.apply_event(server["id"], update)
        row = bridge.server_state(server["id"])["notifications"][key]
        self.assertEqual(row["message"], "two")
        self.assertFalse(row["unread"])
        bridge.apply_event(server["id"], update)
        self.assertEqual(len(bridge.server_state(server["id"])["notifications"]), 1)

        bootstrap = {"event": "message", "id": "added-topic", "time": 3, "topic": "alerts", "message": "cached"}
        bridge.apply_event(server["id"], bootstrap, advance_cursor=False)
        self.assertEqual(bridge.server_state(server["id"])["cursor"], "event-two")
        bridge.apply_event(server["id"], bootstrap, advance_cursor=True)
        self.assertEqual(bridge.server_state(server["id"])["cursor"], "added-topic")

        bridge.apply_event(server["id"], {"event": "message_clear", "id": "clear-id", "topic": "alerts", "sequence_id": "sequence"})
        self.assertNotIn(key, bridge.server_state(server["id"])["notifications"])
        bridge.apply_event(server["id"], {"event": "message", "id": "third", "topic": "alerts", "sequence_id": "delete-me"})
        delete_key = f"{server['id']}:alerts:delete-me"
        bridge.apply_event(server["id"], {"event": "message_delete", "id": "delete-id", "topic": "alerts", "sequence_id": "delete-me"})
        self.assertNotIn(delete_key, bridge.server_state(server["id"])["notifications"])

    def test_read_delete_and_clear_survive_restart(self):
        server = normalize_server({"label": "Home", "baseUrl": "https://example.com", "topics": ["alerts"]})
        config = {"version": 1, "servers": [server]}
        bridge = self.make_bridge(config)
        bridge.apply_event(server["id"], {"event": "message", "id": "first", "topic": "alerts", "message": "one"})
        bridge.apply_event(server["id"], {"event": "message", "id": "second", "topic": "alerts", "message": "two"})
        first_key = f"{server['id']}:alerts:first"
        second_key = f"{server['id']}:alerts:second"
        bridge.mark_notification_read(first_key)
        state = bridge.server_state(server["id"])
        self.assertFalse(state["notifications"][first_key]["unread"])
        self.assertTrue(state["notifications"][second_key]["unread"])
        bridge.delete_notification(first_key)
        bridge.apply_event(server["id"], {"event": "message", "id": "replay", "topic": "alerts",
                                                   "sequence_id": "first", "message": "hidden"})
        self.assertNotIn(first_key, bridge.server_state(server["id"])["notifications"])
        bridge.persist_state()

        restarted = Bridge(self.config_path, self.state_dir, io.StringIO())
        self.bridges.append(restarted)
        self.assertIn("alerts:first", restarted.server_state(server["id"])["dismissed"])
        restarted.clear(server["id"])
        self.assertEqual(restarted.server_state(server["id"])["notifications"], {})

    def test_timed_and_indefinite_mute_state_survives_restart_and_expires(self):
        bridge = self.make_bridge({"version": 1, "servers": []})
        bridge.set_mute(3600)
        mute_until = bridge.current_mute_until()
        self.assertGreater(mute_until, int(time.time()))
        self.assertEqual(bridge.snapshot()["muteUntil"], mute_until)

        restarted = Bridge(self.config_path, self.state_dir, io.StringIO())
        self.bridges.append(restarted)
        self.assertEqual(restarted.current_mute_until(), mute_until)
        restarted.set_mute(-1)
        self.assertEqual(restarted.current_mute_until(), -1)
        restarted.set_mute(0)
        self.assertEqual(restarted.current_mute_until(), 0)
        restarted.state["muteUntil"] = int(time.time()) - 1
        self.assertEqual(restarted.current_mute_until(), 0)

    def test_two_simultaneous_servers_and_auth_error_state(self):
        with RunningServer() as cloud, RunningServer("right-token") as home:
            one = normalize_server({"label": "Cloud", "baseUrl": cloud.url, "topics": ["alerts"]})
            two = normalize_server({"label": "Home", "baseUrl": home.url, "topics": ["backups"],
                                    "auth": {"type": "token", "secret": "right-token"}})
            bridge = self.make_bridge({"version": 1, "servers": [one, two]})
            bridge.start_all()
            self.assertTrue(wait_until(lambda: bridge.statuses.get(one["id"], {}).get("state") == "connected"))
            self.assertTrue(wait_until(lambda: bridge.statuses.get(two["id"], {}).get("state") == "connected"))
            cloud.server.state.emit({"event": "message", "id": "cloud-event", "topic": "alerts", "message": "a"})
            home.server.state.emit({"event": "message", "id": "home-event", "topic": "backups", "message": "b"})
            self.assertTrue(wait_until(lambda: len(bridge.all_rows()) == 2))

        with RunningServer("expected") as protected:
            wrong = normalize_server({"label": "Wrong", "baseUrl": protected.url, "topics": ["alerts"],
                                      "auth": {"type": "token", "secret": "wrong"}})
            other = self.make_bridge({"version": 1, "servers": [wrong]})
            other.start_all()
            self.assertTrue(wait_until(lambda: other.statuses.get(wrong["id"], {}).get("state") == "auth-error"))
            self.assertNotIn("wrong", self.output.getvalue())

    def test_buffered_stream_bootstraps_and_falls_back_to_polling(self):
        old_timeout = bridge_module.STREAM_TIMEOUT_SECONDS
        old_interval = bridge_module.POLL_INTERVAL_SECONDS
        bridge_module.STREAM_TIMEOUT_SECONDS = 0.1
        bridge_module.POLL_INTERVAL_SECONDS = 0.05
        try:
            with RunningServer(buffered_stream=True) as buffered:
                buffered.server.state.emit({
                    "event": "message", "id": "cached-event", "topic": "alerts",
                    "message": "cached",
                })
                server = normalize_server({
                    "label": "Buffered", "baseUrl": buffered.url, "topics": ["alerts"],
                })
                bridge = self.make_bridge({"version": 1, "servers": [server]})
                bridge.start_all()
                self.assertTrue(wait_until(
                    lambda: bridge.server_state(server["id"]).get("cursor") == "cached-event"
                ))

                buffered.server.state.emit({
                    "event": "message", "id": "polled-event", "topic": "alerts",
                    "message": "polled",
                })
                self.assertTrue(wait_until(
                    lambda: any(row["id"] == "polled-event" for row in bridge.all_rows())
                ))
                self.assertEqual(bridge.statuses[server["id"]]["state"], "connected")
        finally:
            bridge_module.STREAM_TIMEOUT_SECONDS = old_timeout
            bridge_module.POLL_INTERVAL_SECONDS = old_interval

    def test_http_action_gating_default_post_and_correlated_results(self):
        with RunningServer() as target:
            server = normalize_server({"label": "Home", "baseUrl": target.url, "topics": ["alerts"],
                                       "enabled": False, "allowHttpActions": False})
            bridge = self.make_bridge({"version": 1, "servers": [server]})
            bridge.apply_event(server["id"], {"event": "message", "id": "action-row", "topic": "alerts",
                "actions": [{"id": "http-one", "action": "http", "label": "Ack",
                             "url": target.url + "/action-target", "body": "{\"ok\":true}"}]})
            key = f"{server['id']}:alerts:action-row"
            bridge.perform_action("blocked", key, "http-one")
            self.assertTrue(wait_until(lambda: any(event.get("requestId") == "blocked" for event in self.events())))
            blocked = next(event for event in self.events() if event.get("requestId") == "blocked")
            self.assertFalse(blocked["ok"])
            self.assertEqual(target.server.state.actions, [])

            server["allowHttpActions"] = True
            bridge.config["servers"][0]["allowHttpActions"] = True
            bridge.perform_action("allowed", key, "http-one")
            self.assertTrue(wait_until(lambda: any(event.get("requestId") == "allowed" for event in self.events())))
            allowed = next(event for event in self.events() if event.get("requestId") == "allowed")
            self.assertTrue(allowed["ok"])
            self.assertEqual(allowed["status"], 204)
            self.assertEqual(target.server.state.actions[-1]["method"], "POST")
            self.assertEqual(target.server.state.actions[-1]["body"], '{"ok":true}')

    def test_media_allows_only_configured_origin_and_rejects_cross_origin_redirects(self):
        with RunningServer("media-token") as source, RunningServer() as target:
            server = normalize_server({"label": "Media", "baseUrl": source.url + "/proxy", "topics": ["alerts"],
                                       "enabled": False, "auth": {"type": "token", "secret": "media-token"}})
            bridge = self.make_bridge({"version": 1, "servers": [server]})
            same = bridge.download_media(server, "icon", source.url + "/icon.png")
            self.assertTrue(same.exists())
            self.assertEqual(stat.S_IMODE(same.stat().st_mode), 0o600)

            same_redirect = source.url + "/redirect?" + urllib.parse.urlencode({"to": source.url + "/icon.png"})
            redirected = bridge.download_media(server, "icon", same_redirect)
            self.assertTrue(redirected.exists())

            with self.assertRaisesRegex(MediaError, "configured server origin"):
                bridge.download_media(server, "icon", target.url + "/capture.png")
            self.assertEqual(target.server.state.actions, [])

            cross_redirect = source.url + "/redirect?" + urllib.parse.urlencode({"to": target.url + "/capture.png"})
            with self.assertRaisesRegex(MediaError, "configured server origin"):
                bridge.download_media(server, "icon", cross_redirect)
            self.assertEqual(target.server.state.actions, [])

            with self.assertRaises(MediaError):
                bridge.download_media(server, "icon", source.url + "/huge.png")
            with self.assertRaises(MediaError):
                bridge.download_media(server, "icon", source.url + "/oversized.png")
            with self.assertRaises(MediaError):
                bridge.download_media(server, "icon", source.url + "/bad-media")

            old_limit = bridge_module.MAX_MEDIA_CACHE
            bridge_module.MAX_MEDIA_CACHE = 10
            try:
                extra = bridge.media_dir / "unreferenced.bin"
                extra.write_bytes(b"x" * 20)
                bridge.enforce_media_cache()
                self.assertFalse(extra.exists())
            finally:
                bridge_module.MAX_MEDIA_CACHE = old_limit

    def test_save_delete_results_and_malformed_config_protection(self):
        bridge = self.make_bridge({"version": 1, "servers": []})
        candidate = {"label": "Offline", "baseUrl": "https://example.com", "topics": ["alerts"], "enabled": False}
        bridge.save_server("save-ok", candidate)
        saved = next(event for event in self.events() if event.get("requestId") == "save-ok")
        self.assertTrue(saved["ok"])
        server_id = saved["server"]["id"]
        bridge.delete_server("delete-ok", server_id)
        deleted = next(event for event in self.events() if event.get("requestId") == "delete-ok")
        self.assertTrue(deleted["ok"])
        self.assertEqual(deleted["deletedServerId"], server_id)
        bridge.delete_server("delete-bad", server_id)
        self.assertFalse(next(event for event in self.events() if event.get("requestId") == "delete-bad")["ok"])

        malformed_path = Path(self.temp.name) / "malformed.json"
        malformed_path.write_text("{bad", encoding="utf-8")
        malformed = Bridge(malformed_path, Path(self.temp.name) / "malformed-state", io.StringIO())
        self.bridges.append(malformed)
        malformed.save_server("no-overwrite", candidate)
        self.assertEqual(malformed_path.read_text(encoding="utf-8"), "{bad")

    def test_json_lines_subprocess_correlates_commands_and_exits_zero(self):
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(Path(self.temp.name) / "sub-config")
        env["XDG_STATE_HOME"] = str(Path(self.temp.name) / "sub-state")
        command = json.dumps({"cmd": "save_server", "requestId": "sub-save", "server": {
            "label": "Offline", "baseUrl": "https://example.com", "topics": ["alerts"], "enabled": False
        }}) + "\n"
        process = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "ntfy_bridge.py")],
                                 input=command, text=True, capture_output=True, env=env, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        events = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual(events[0]["event"], "snapshot")
        result = next(event for event in events if event.get("requestId") == "sub-save")
        self.assertEqual(result["event"], "config_result")
        self.assertTrue(result["ok"])
        self.assertTrue(any(event["event"] == "snapshot" and event["servers"] for event in events[1:]))


if __name__ == "__main__":
    unittest.main()
