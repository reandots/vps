from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        operations = list(task_vars.get("test_service_operations", []))
        operations.append(self._task.args)
        return {
            "changed": False,
            "ansible_facts": {"test_service_operations": operations},
        }
