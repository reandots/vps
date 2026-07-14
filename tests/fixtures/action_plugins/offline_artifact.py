from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if self._task.args["test_module"] == "get_url" and task_vars.get("test_download_fails", False):
            return {"failed": True, "changed": False, "msg": "Simulated archive verification failure"}
        operations = list(task_vars.get("test_artifact_operations", []))
        operations.append(self._task.args)
        return {
            "changed": False,
            "ansible_facts": {"test_artifact_operations": operations},
        }
