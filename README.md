# VPS Ansible Repository

Репозиторий предназначен для настройки и сопровождения домашних VPS через Ansible.

Он покрывает два этапа:

- `bootstrap` - первый вход на новый сервер, перенос на SSH-ключ, отключение входа по паролю, смена SSH порта
- `provision` - дальнейшая настройка сервера и сервисов, например Xray VLESS+Reality

## Первый запуск репозитория

Установить Ansible collections:

```bash
just install
```

Посмотреть доступные команды:

```bash
just --list
```

## Как добавить новый VPS

Везде далее буду приводить пример на основе сервера `example`.

Создать SSH ключ:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/example -C "example-server"
```

Получить хеш от пароля для пользователя на сервере, этот пользователь будет создаваться при развёртывании, его имя ниже будет заполняться в настройках, а хеш можно получить выполнив команду и введя при запросе пароль для хеширования:

```bash
just hash-password
```

Если нужен VLESS, то сгенерировать для него данные:

```bash
xray uuid
xray x25519
openssl rand -hex 8
```

Прописать по аналогии в `justfile` новый хост.

Прописать хост в `ansible/inventories/hosts.yml`, тут нужно добавить в группу xray, если нам нужно устанавливать xray.

Создать в `ansible/inventories/host_vars` новую директорию для сервера и заполнить.

В `main.yml` по сути проставляем имя ssh ключа и какие роли применять, например:

```yaml
---
ssh_key_name: example
ufw_enabled: true
fail2ban_enabled: true
bbr_enabled: true
unattended_upgrades_enabled: true
xray_enabled: true
```

В `vault.example.yml` по сути просто пример того, какие данные нужно хранить в зашифрованном `vault.yml`, типично структура вот такая:

```yaml
---
ansible_host: 1.2.3.4
ssh_port: 2222
server_admin_user: user
server_admin_password_hash: $REPLACE_WITH_SHA512_PASSWORD_HASH
xray_vless_uuid: 11111111-2222-3333-4444-555555555555
xray_reality_private_key: REPLACE_WITH_REAL_PRIVATE_KEY
xray_reality_public_key: REPLACE_WITH_REAL_PUBLIC_KEY
xray_reality_short_ids:
  - a1b2c3d4e5f67890
xray_reality_dest: example.com:443
xray_reality_server_names:
  - example.com
```

В зашифрованном файле мы заполняем сгенерённые выше сведения. В том числе подбираем и прописываем SNI для сервера. Затем шифруем `vault.yml`:

```bash
just vault-edit ansible/inventories/host_vars/vps-example/vault.yml
```

Непосредственное развёртывание выполняется в 2 этапа вот такими командами:

```bash
just bootstrap-example
just provision-example
```

