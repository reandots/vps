from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        path = self._task.args["path"]
        return {
            "changed": False,
            "stat": task_vars.get("test_stats", {}).get(path, {
                "exists": task_vars.get("test_files_exist", False),
                "isdir": path == task_vars.get("test_directory_path"),
            }),
        }
