"""Offline regression checks; never load Vault or connect to a VPS."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def load_yaml(path):
    return yaml.safe_load(path.read_text())


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vps-tests-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        config = self.directory / "ansible.cfg"
        config.write_text(
            "[defaults]\n"
            f"roles_path = {self.directory / 'roles'}:{ROOT / 'ansible/roles'}\n"
            f"action_plugins = {FIXTURES / 'action_plugins'}\n"
            f"connection_plugins = {FIXTURES / 'connection_plugins'}\n"
            f"local_tmp = {self.directory / 'tmp'}\n"
            "retry_files_enabled = False\n"
            "host_key_checking = True\n"
        )
        self.env = dict(os.environ, ANSIBLE_CONFIG=str(config), ANSIBLE_NOCOLOR="1")

    def run_ansible(self, *args, expected_returncode=0):
        result = subprocess.run(
            args, cwd=self.directory, env=self.env,
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, expected_returncode, result.stdout + result.stderr)
        return result.stdout

    def prepare_mock_roles(self, roles=("fail2ban", "xray_vless_reality")):
        # FQCN builtins cannot be shadowed by local action plugins. Substitute
        # simulated modules only in temporary copies of the real roles.
        for role in roles:
            target = self.directory / "roles" / role
            shutil.copytree(ROOT / "ansible/roles" / role, target)
            for path in target.rglob("*.yml"):
                content = path.read_text()
                for module in ("service_facts", "systemd", "file", "apt", "stat", "command", "tempfile"):
                    content = content.replace(f"ansible.builtin.{module}:", f"offline_{module}:")
                tasks = yaml.safe_load(content)

                def substitute_artifacts(tasks):
                    for task in tasks:
                        for module in ("get_url", "unarchive", "copy"):
                            args = task.pop(f"ansible.builtin.{module}", None)
                            if args is not None:
                                task["offline_artifact"] = dict(args, test_module=module)
                        for section in ("block", "rescue", "always"):
                            if section in task:
                                substitute_artifacts(task[section])

                # Only task/handler lists contain module calls; defaults are mappings.
                if isinstance(tasks, list):
                    substitute_artifacts(tasks)
                path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    def write_lifecycle_playbook(self, tasks=None, roles=None):
        provision = load_yaml(ROOT / "ansible/playbooks/provision.yml")[0]
        if roles is None:
            roles = [role for role in provision["roles"] if role["role"] in ("fail2ban", "xray_vless_reality")]
        playbook = self.directory / "lifecycle.yml"
        playbook.write_text(yaml.safe_dump([{
            "name": "Test service lifecycle offline", "hosts": "all", "gather_facts": False,
            "pre_tasks": [{"name": "Inject synthetic facts", "ansible.builtin.set_fact": {
                "ansible_facts": "{{ test_facts | default({}) }}",
            }}],
            "roles": roles, "tasks": tasks or [],
        }]))
        return playbook

    def write_inventory(self, cases):
        cases = {host: dict(variables) for host, variables in cases.items()}
        for variables in cases.values():
            if "ansible_facts" in variables:
                variables["test_facts"] = variables.pop("ansible_facts")
        variables = load_yaml(ROOT / "ansible/inventories/group_vars/all/main.yml")
        variables.update(ansible_connection="offline_guard", xray_state="disabled", fail2ban_state="disabled")
        inventory = self.directory / "hosts.yml"
        inventory.write_text(yaml.safe_dump({"all": {
            "vars": variables,
            # Old group membership must not override the desired state.
            "children": {"xray": {"hosts": cases}},
        }}))
        return inventory

    def test_examples_are_outside_live_inventory(self):
        inventory_dir = ROOT / "ansible/inventories"
        self.assertEqual(list(inventory_dir.rglob("*.example.yml")), [])
        inventory = load_yaml(inventory_dir / "hosts.yml")
        groups = inventory["all"].get("children", {})
        self.assertNotIn("xray", groups)
        self.assertNotIn("base", groups)
        hosts = inventory["all"]["hosts"]
        self.assertEqual(set(hosts), {"vps-hshp", "vps-litnets"})
        self.assertNotIn("vps-example", hosts)
        self.assertFalse((inventory_dir / "host_vars/vps-example/main.yml").exists())
        self.assertTrue((ROOT / "ansible/examples/host_vars/vps-example/vault.example.yml").exists())

        # Copy only public main.yml files, never read or decrypt Vault files.
        for path in inventory_dir.rglob("main.yml"):
            target = self.directory / path.relative_to(inventory_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text())
        target = self.directory / "hosts.yml"
        target.write_text(yaml.safe_dump(inventory))
        data = json.loads(self.run_ansible("ansible-inventory", "-i", str(target), "--list"))
        self.assertEqual(set(data["_meta"]["hostvars"]), set(hosts))
        for variables in data["_meta"]["hostvars"].values():
            self.assertNotIn("ansible_host", variables)
            self.assertNotIn("server_admin_password_hash", variables)
            self.assertNotIn("xray_vless_uuid", variables)
            self.assertNotIn("xray_reality_private_key", variables)
            self.assertEqual(variables["xray_state"], "enabled")
            self.assertEqual(variables["fail2ban_state"], "enabled")
            for legacy in ("xray_enabled", "xray_managed", "fail2ban_enabled", "fail2ban_managed"):
                self.assertNotIn(legacy, variables)

    def test_playbook_syntax(self):
        for name in ("bootstrap", "provision", "upgrade"):
            with self.subTest(playbook=name):
                self.run_ansible(
                    "ansible-playbook", "-i", "localhost,", "--syntax-check",
                    str(ROOT / f"ansible/playbooks/{name}.yml"),
                )

    def test_service_lifecycle_without_remote_execution(self):
        self.prepare_mock_roles()
        installed = {
            "xray.service": {"status": "enabled", "state": "running", "source": "systemd"},
            "fail2ban.service": {"status": "enabled", "state": "running", "source": "systemd"},
        }
        stop_xray = {"name": "xray", "enabled": False, "state": "stopped"}
        stop_fail2ban = {"name": "fail2ban", "enabled": False, "state": "stopped"}
        cases = {
            "installed": {"test_services": installed, "expected": [stop_fail2ban, stop_xray]},
            "absent": {"test_services": {}, "expected": []},
            "not_found": {
                "test_services": {key: dict(value, status="not-found") for key, value in installed.items()},
                "expected": [],
            },
            "custom_name": {
                "xray_service_name": "custom-xray",
                "test_services": {"custom-xray.service": installed["xray.service"]},
                "expected": [{"name": "custom-xray", "enabled": False, "state": "stopped"}],
            },
        }
        xray_files = [
            "/usr/local/bin/xray", "/usr/local/bin/geoip.dat", "/usr/local/bin/geosite.dat",
            "/usr/local/etc/xray/config.json", "/usr/local/share/xray-version",
            "/etc/systemd/system/xray.service",
        ]
        for installed_files in (True, False):
            cases[f"removed_files_{installed_files}"] = {
                "xray_state": "removed", "fail2ban_state": "removed",
                "test_services": installed if installed_files else {},
                "test_files_exist": installed_files,
                "expected": [stop_fail2ban, stop_xray] if installed_files else [],
                "expected_files": [{"path": path, "state": "absent"} for path in ["/etc/fail2ban/jail.local", *xray_files]],
                "expected_apt": [{"name": "fail2ban", "state": "absent", "purge": False, "autoremove": False}],
            }
        cases["mixed"] = {
            "xray_state": "removed", "test_services": installed, "test_files_exist": True,
            "expected": [stop_fail2ban, stop_xray],
            "expected_files": [{"path": path, "state": "absent"} for path in xray_files],
        }
        cases["removed_custom_paths"] = {
            "xray_state": "removed", "xray_service_name": "custom-xray",
            "xray_install_dir": "/opt/xray/bin", "xray_config_dir": "/etc/custom-xray",
            "xray_version_file": "/opt/xray/version", "test_files_exist": True,
            "test_services": {"custom-xray.service": installed["xray.service"]},
            "expected": [{"name": "custom-xray", "enabled": False, "state": "stopped"}],
            "expected_files": [{"path": path, "state": "absent"} for path in (
                "/opt/xray/bin/xray", "/opt/xray/bin/geoip.dat", "/opt/xray/bin/geosite.dat",
                "/etc/custom-xray/config.json", "/opt/xray/version",
                "/etc/systemd/system/custom-xray.service",
            )],
        }
        inventory = self.write_inventory(cases)
        playbook = self.write_lifecycle_playbook([
            {"name": "Flush removal handlers", "ansible.builtin.meta": "flush_handlers"},
            {"name": "Check exact lifecycle operations", "ansible.builtin.assert": {
                "that": [
                    "test_service_operations | default([]) == expected + ([{'daemon_reload': true}] if xray_state == 'removed' and test_files_exist | default(false) else [])",
                    "test_file_operations | default([]) == expected_files | default([])",
                    "test_apt_operations | default([]) == expected_apt | default([])",
                ],
            }},
        ])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook))
        for case in cases:
            self.assertIn(case, output)

    def test_invalid_and_legacy_states_are_rejected(self):
        self.prepare_mock_roles()
        for prefix, role in (("xray", "xray_vless_reality"), ("fail2ban", "fail2ban")):
            with self.subTest(role=role):
                cases = {
                    "invalid": {f"{prefix}_state": "typo"},
                    "legacy_enabled": {f"{prefix}_enabled": False},
                    "legacy_managed": {f"{prefix}_managed": False},
                }
                inventory = self.write_inventory(cases)
                playbook = self.write_lifecycle_playbook(roles=[{"role": role}])
                output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
                self.assertIn(f"Use {prefix}_state:", output)
                self.assertNotIn("Gather service facts", output)

    def test_removal_refuses_directories(self):
        self.prepare_mock_roles()
        for prefix, role, path in (
            ("xray", "xray_vless_reality", "/usr/local/bin/xray"),
            ("fail2ban", "fail2ban", "/etc/fail2ban/jail.local"),
        ):
            with self.subTest(role=role):
                inventory = self.write_inventory({"unsafe": {
                    f"{prefix}_state": "removed", "test_directory_path": path,
                }})
                playbook = self.write_lifecycle_playbook(roles=[{"role": role}])
                output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
                self.assertIn("not directories" if prefix == "xray" else "not a directory", output)
                self.assertNotIn(f"TASK [{role} : Remove managed", output)

    def test_provision_installs_packages_without_upgrading(self):
        self.prepare_mock_roles(roles=("base_system",))
        inventory = self.write_inventory({"base": {}})
        playbook = self.write_lifecycle_playbook(roles=[{"role": "base_system"}], tasks=[{
            "name": "Ensure package provisioning does not upgrade the system",
            "ansible.builtin.assert": {"that": [
                "test_apt_operations | length == 1",
                "test_apt_operations[0].state == 'present'",
                "'upgrade' not in test_apt_operations[0]",
                "'unzip' in test_apt_operations[0].name",
                "'micro' in test_apt_operations[0].name",
                "test_apt_operations[0].cache_valid_time == 3600",
            ]},
        }])
        self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook))

    def test_upgrade_is_an_explicit_separate_workflow(self):
        play = load_yaml(ROOT / "ansible/playbooks/upgrade.yml")[0]
        tasks = []
        for task in play["tasks"]:
            task = dict(task)
            for module in ("apt", "stat"):
                if f"ansible.builtin.{module}" in task:
                    task[f"offline_{module}"] = task.pop(f"ansible.builtin.{module}")
            tasks.append(task)
        playbook = self.write_lifecycle_playbook(roles=[], tasks=tasks + [{
            "name": "Check explicit full upgrade",
            "ansible.builtin.assert": {"that": [
                "test_apt_operations == [{'update_cache': true, 'upgrade': 'full'}]",
            ]},
        }])
        inventory = self.write_inventory({"upgrade": {}})
        self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook))

    def test_legacy_upgrade_flag_is_rejected(self):
        self.prepare_mock_roles(roles=("base_system",))
        inventory = self.write_inventory({
            "old_enabled": {"base_upgrade_packages": True},
            "old_disabled": {"base_upgrade_packages": False},
        })
        playbook = self.write_lifecycle_playbook(roles=[{"role": "base_system"}])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
        self.assertIn("Remove base_upgrade_packages", output)
        self.assertNotIn("Update apt cache and install base packages", output)

    def test_xray_inspection_and_verified_installation(self):
        self.prepare_mock_roles()
        healthy = {"exists": True, "isreg": True, "size": 100, "executable": True}
        stats = {f"/usr/local/bin/{name}": healthy for name in ("xray", "geoip.dat", "geosite.dat")}
        cases = {
            "healthy": {"test_stats": stats, "expected_repair": False},
            "binary_missing": {"test_stats": dict(stats, **{"/usr/local/bin/xray": {"exists": False}}), "expected_repair": True},
            "binary_broken": {"test_stats": stats, "test_binary_rc": 126, "expected_repair": True},
            "binary_not_executable": {"test_stats": dict(stats, **{"/usr/local/bin/xray": dict(healthy, executable=False)}), "expected_repair": True},
            "old_version": {"test_stats": stats, "test_binary_stdout": "Xray 25.1.1", "expected_repair": True},
            "data_missing": {"test_stats": dict(stats, **{"/usr/local/bin/geoip.dat": {"exists": False}}), "expected_repair": True},
            "data_empty": {"test_stats": dict(stats, **{"/usr/local/bin/geosite.dat": dict(healthy, size=0)}), "expected_repair": True},
            "arm64": {"ansible_facts": {"architecture": "aarch64"}, "test_stats": stats, "test_binary_stdout": "Xray 25.1.1", "expected_repair": True},
        }
        for case in cases.values():
            case.setdefault("ansible_facts", {"architecture": "x86_64"})
        inventory = self.write_inventory(cases)
        playbook = self.write_lifecycle_playbook(roles=[], tasks=[
            {"name": "Inspect Xray", "ansible.builtin.include_role": {"name": "xray_vless_reality", "tasks_from": "inspect", "public": True}},
            {"name": "Install verified Xray if needed", "ansible.builtin.include_role": {"name": "xray_vless_reality", "tasks_from": "install"}, "when": "xray_install_required"},
            {"name": "Verify installation decision", "ansible.builtin.assert": {"that": [
                "xray_install_required == expected_repair",
                "test_artifact_operations | default([]) | length == (5 if expected_repair else 0)",
                "not expected_repair or test_artifact_operations[0].test_module == 'get_url'",
                "not expected_repair or test_artifact_operations[0].checksum == xray_release_checksum",
                "not expected_repair or ('Xray-' + xray_arch + '.zip') in test_artifact_operations[0].url",
                "not expected_repair or test_file_operations[-1] == {'path': '/tmp/offline-xray', 'state': 'absent'}",
            ]}},
        ])
        self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook))

    def test_xray_rejects_unknown_architecture_or_checksum(self):
        self.prepare_mock_roles()
        inventory = self.write_inventory({
            "unknown_arch": {"ansible_facts": {"architecture": "unknown"}},
            "unknown_version": {"ansible_facts": {"architecture": "x86_64"}, "xray_version": "99.1.1"},
        })
        playbook = self.write_lifecycle_playbook(roles=[], tasks=[{
            "name": "Inspect Xray", "ansible.builtin.include_role": {"name": "xray_vless_reality", "tasks_from": "inspect"},
        }])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
        self.assertIn("Unsupported architecture or missing checksum", output)
        self.assertNotIn("Inspect installed Xray artifacts", output)

    def test_xray_staged_version_mismatch_keeps_installed_files(self):
        self.prepare_mock_roles()
        inventory = self.write_inventory({"mismatch": {
            "ansible_facts": {"architecture": "x86_64"}, "test_staged_stdout": "Xray 25.1.1",
        }})
        playbook = self.write_lifecycle_playbook(roles=[], tasks=[{
            "name": "Install Xray", "ansible.builtin.include_role": {"name": "xray_vless_reality", "tasks_from": "install"},
        }])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
        self.assertIn("does not report the requested version", output)
        self.assertIn("Remove private Xray staging directory", output)
        self.assertNotIn("Install verified Xray binary and data", output)

    def test_xray_check_mode_reports_repair_without_installation(self):
        self.prepare_mock_roles()
        inventory = self.write_inventory({"check": {
            "ansible_facts": {"architecture": "x86_64"}, "xray_state": "enabled",
            "xray_vless_uuid": "11111111-2222-3333-4444-555555555555",
            "xray_reality_private_key": "test-only-placeholder",
            "xray_reality_short_ids": ["0123456789abcdef"],
        }})
        playbook = self.write_lifecycle_playbook(roles=[{"role": "xray_vless_reality"}], tasks=[{
            "name": "Check mode does not mutate missing installation",
            "ansible.builtin.assert": {"that": [
                "xray_install_required",
                "test_file_operations is not defined",
                "test_artifact_operations is not defined",
                "test_service_operations is not defined",
            ]},
        }])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), "--check", str(playbook))
        self.assertIn("Xray installation or repair is required", output)

    def test_xray_failed_download_cleans_staging(self):
        self.prepare_mock_roles()
        inventory = self.write_inventory({"bad_download": {
            "ansible_facts": {"architecture": "x86_64"}, "test_download_fails": True,
        }})
        playbook = self.write_lifecycle_playbook(roles=[], tasks=[{
            "name": "Install Xray", "ansible.builtin.include_role": {"name": "xray_vless_reality", "tasks_from": "install"},
        }])
        output = self.run_ansible("ansible-playbook", "-i", str(inventory), str(playbook), expected_returncode=2)
        self.assertIn("Simulated archive verification failure", output)
        self.assertIn("Remove private Xray staging directory", output)
        self.assertNotIn("Unpack verified Xray release", output)


if __name__ == "__main__":
    unittest.main()
