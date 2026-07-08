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

Прописать хост `vps-example` в секции `all.hosts` в `ansible/inventories/hosts.yml`. Состояние Xray задаётся через `xray_state`, не через группы.

Создать в `ansible/inventories/host_vars` новую директорию для сервера и заполнить. Шаблон находится в `ansible/examples/host_vars/vps-example/`; сам `vps-example` отсутствует в рабочем inventory и готовых recipes. Команды ниже станут доступны после добавления хоста и его recipes.

В `main.yml` по сути проставляем имя ssh ключа и какие роли применять, например:

```yaml
---
ssh_key_name: example
ufw_enabled: true
fail2ban_state: enabled
bbr_enabled: true
unattended_upgrades_enabled: true
xray_state: enabled
```

В `ansible/examples/host_vars/vps-example/vault.example.yml` находится пример данных для зашифрованного `vault.yml`, типично структура вот такая:

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

Создать `vault.yml` по примеру и заполнить сгенерированные сведения, в том числе SNI для сервера. В каталоги inventory копировать только `main.yml` и заполненный `vault.yml`, не `vault.example.yml`: Ansible загружает все YAML-файлы из каталогов vars. Перед добавлением файла в Git зашифровать его:

```bash
ansible-vault encrypt ansible/inventories/host_vars/vps-example/vault.yml
```

Для последующего редактирования уже зашифрованного файла:

```bash
just vault-edit ansible/inventories/host_vars/vps-example/vault.yml
```

Непосредственное развёртывание выполняется в 2 этапа вот такими командами:

```bash
just bootstrap-example
just provision-example
```

**Важно:** текущие команды bootstrap/provision используют `--diff`. Вывод секретного конфига Xray скрыт, но при добавлении других секретных конфигов им нужна аналогичная защита; не публикуйте вывод с секретами и проверяйте логи. Примеры из `ansible/examples/` не загружаются Ansible; не переносите заглушки в рабочую конфигурацию.

## Состояния сервисов

Xray и fail2ban всегда управляются Ansible. Для каждого сервиса задаётся одна переменная: `xray_state` или `fail2ban_state`.

| Значение | Поведение при provision |
| --- | --- |
| `enabled` | Установить, настроить и запустить сервис, включить автозапуск |
| `disabled` | Остановить существующий сервис и выключить автозапуск, сохранив установку и конфиги |
| `removed` | Остановить сервис, выключить автозапуск и удалить установку и конфиги, принадлежащие роли |

По умолчанию `xray_state: disabled`, `fail2ban_state: enabled`; у текущих VPS оба сервиса включены в host vars. Например, в `host_vars/<host>/main.yml`:

```yaml
xray_state: disabled
fail2ban_state: enabled
```

Затем выполнить `just provision-<suffix>`. Для удаления вместо `disabled` задать `removed`. Секреты Xray для отключения и удаления не нужны, но Vault с параметрами подключения по-прежнему нужен. Отсутствующий сервис не устанавливается в этих состояниях.

При удалении Xray убираются его бинарник, `geoip.dat`, `geosite.dat`, `config.json`, marker версии и systemd unit по настроенным путям. Общие каталоги не удаляются. Для fail2ban удаляются пакет без autoremove/purge и управляемый `/etc/fail2ban/jail.local`; общие зависимости и остальные файлы конфигурации пакета сохраняются. Секреты в Vault, firewall-правила и временные архивы установки не удаляются.

Прежние `xray_enabled`, `fail2ban_enabled` и `*_managed` больше не поддерживаются: роль завершится с сообщением о необходимости заменить их на `*_state`. Если они были заданы в Vault, оператору нужно обновить их через `just vault-edit`.

**Ограничения:** `ufw_enabled`, `bbr_enabled` и `unattended_upgrades_enabled` пока только включают или пропускают роли: `false` не отменяет уже применённые настройки. Отключение Xray не закрывает firewall-порты. Не выключайте fail2ban без понимания последствий для защиты SSH.

Обычный `provision` не применяет изменения SSH и admin-пользователя — эти роли входят только в `bootstrap`. Полное обновление пакетов при provision пока сохраняется; его можно пропустить через `base_upgrade_packages: false`.

## Локальные проверки

```bash
just test
```

Нужны Ansible, установленные collections и Python с PyYAML. Проверяются синтаксис playbooks, изоляция примеров, отключение и удаление сервисов, отказ при ошибочных/устаревших переменных и защита от удаления каталогов. Работа с systemd, пакетами и файлами имитируется, выполнение реальных команд и передача файлов заблокированы. Vault не читается, подключения к VPS нет; эти проверки не заменяют проверку на сервере.
