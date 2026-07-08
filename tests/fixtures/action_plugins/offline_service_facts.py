from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        return {
            "changed": False,
            "ansible_facts": {"services": task_vars.get("test_services", {})},
        }
