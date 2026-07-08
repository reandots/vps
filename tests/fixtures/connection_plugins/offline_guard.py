from ansible.errors import AnsibleConnectionFailure
from ansible.plugins.connection import ConnectionBase


class Connection(ConnectionBase):
    transport = "offline_guard"
    has_pipelining = False

    def _connect(self):
        self._connected = True
        return self

    def exec_command(self, cmd, in_data=None, sudoable=True):
        raise AnsibleConnectionFailure("Offline test attempted to execute a real command")

    def put_file(self, in_path, out_path):
        raise AnsibleConnectionFailure("Offline test attempted to transfer a file")

    def fetch_file(self, in_path, out_path):
        raise AnsibleConnectionFailure("Offline test attempted to fetch a file")

    def close(self):
        self._connected = False
