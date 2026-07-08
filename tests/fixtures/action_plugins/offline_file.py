from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        operations = list(task_vars.get("test_file_operations", []))
        operations.append(self._task.args)
        return {
            "changed": task_vars.get("test_files_exist", False),
            "ansible_facts": {"test_file_operations": operations},
        }
