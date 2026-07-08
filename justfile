set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

inventory := "ansible/inventories/hosts.yml"
playbook_dir := "ansible/playbooks"
vault_arg := "--ask-vault-pass"
become_arg := "--ask-become-pass"

hshp_host := "vps-hshp"
litnets_host := "vps-litnets"

install:
    ansible-galaxy collection install -r requirements.yml

test:
    python3 -m unittest discover -s tests -v

hash-password:
    openssl passwd -6

ping-hshp:
    ansible all -i {{ inventory }} {{ vault_arg }} --limit {{ hshp_host }} -m ping

ping-litnets:
    ansible all -i {{ inventory }} {{ vault_arg }} --limit {{ litnets_host }} -m ping

bootstrap-hshp:
    ansible-playbook -i {{ inventory }} {{ vault_arg }} {{ playbook_dir }}/bootstrap.yml --limit {{ hshp_host }} --diff

bootstrap-litnets:
    ansible-playbook -i {{ inventory }} {{ vault_arg }} {{ playbook_dir }}/bootstrap.yml --limit {{ litnets_host }} --diff

provision-hshp:
    ansible-playbook -i {{ inventory }} {{ vault_arg }} {{ become_arg }} {{ playbook_dir }}/provision.yml --limit {{ hshp_host }} --diff

provision-litnets:
    ansible-playbook -i {{ inventory }} {{ vault_arg }} {{ become_arg }} {{ playbook_dir }}/provision.yml --limit {{ litnets_host }} --diff

vault-edit FILE:
    ansible-vault edit {{ FILE }}

vault-view FILE:
    ansible-vault view {{ FILE }}
