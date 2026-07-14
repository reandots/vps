from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        operations = list(task_vars.get("test_command_operations", []))
        operations.append(self._task.args)
        staged = self._task.args["argv"][0].startswith("/tmp/offline-xray/")
        return {
            "changed": False,
            "rc": task_vars.get("test_staged_rc" if staged else "test_binary_rc", 0),
            "stdout": task_vars.get("test_staged_stdout" if staged else "test_binary_stdout", "Xray 26.3.27 (Xray, Penetrates Everything.)"),
            "ansible_facts": {"test_command_operations": operations},
        }
