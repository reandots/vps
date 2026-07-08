from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        return {
            "changed": False,
            "stat": {
                "exists": task_vars.get("test_files_exist", False),
                "isdir": self._task.args["path"] == task_vars.get("test_directory_path"),
            },
        }
