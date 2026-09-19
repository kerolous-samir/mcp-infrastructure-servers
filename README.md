# MCP Infrastructure Servers

Five [Model Context Protocol](https://modelcontextprotocol.io) servers that expose
infrastructure tooling — libvirt/KVM, Active Directory, WinRM, PostgreSQL and shell — as
tools an AI agent can call.

---
These servers ran in production inside a multi-tenant virtualization platform before being extracted, de-branded and released here.
---

## What MCP is

The Model Context Protocol is an open standard that lets an AI model call tools provided by
a separate server process, communicating over stdio or HTTP with JSON-RPC. A server declares
the tools it offers and their input schemas; the client (Claude Desktop, an IDE extension, or
your own agent) decides when to invoke them and passes the results back to the model.

## The servers

| Server | Tools | Exposes |
|---|---:|---|
| `servers/libvirt` | 52 | VM lifecycle (start/stop/reboot/force-stop/delete), creation and cloning, golden images, snapshots, storage pools and volumes, virtual networks and bridges, VNC/console URIs, DHCP leases, remote hypervisor registration, host OS queries and network configuration |
| `servers/active_directory` | 50 | Users, groups, OUs and computers (create/read/update/delete/search), password reset and unlock, account enable/disable, GPO create/link/backup/restore, DNS zones and records, DHCP scopes, leases and reservations, domain and forest info, DC registration |
| `servers/winrm` | 34 | Remote command and PowerShell execution on Windows hosts, file upload/download/delete, directory listing, service and process control, local users and groups, network adapters, DNS and hostname configuration, disks and volumes, event logs, system info, reboot and shutdown |
| `servers/sql` | 36 | PostgreSQL connection management, parameterised queries and statements, table listing and introspection, table statistics, schema initialisation, database backup, plus CRUD and search over a simple host/VM/network/user inventory |
| `servers/bash` | 37 | Command and script execution locally or over SSH, file read/write/copy/move/delete and search, systemd service control, process listing and termination, user management, interfaces/routes/ping, disk usage and mounts, package management, hostname and uptime |

**209 tools total** (171 distinct names — some, such as `list_services` and `add_host`, appear
in more than one server). Every count above was taken from a live `tools/list` response over
stdio, not from reading the source.

## Installation

Requires Python 3.10+. The libvirt server additionally needs libvirt development headers
(`libvirt-dev` on Debian/Ubuntu, `libvirt-devel` on RHEL family) for `libvirt-python` to build.

```bash
git clone https://github.com/kerolous-samir/mcp-infrastructure-servers.git
cd mcp-infrastructure-servers
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`requirements.txt` pins `mcp>=1.27.2,<2` deliberately. The 2.x release renamed
`Tool.inputSchema` to `Tool.input_schema` and removed `Server.list_tools`; these servers target
the 1.x API and every one of them fails to list tools against 2.x.

You only need the dependencies for the servers you intend to run. Installing just one:

```bash
.venv/bin/pip install "mcp>=1.27.2,<2" ldap3 pywinrm requests requests_ntlm   # active_directory
```

## Configuration

Every server is configured entirely through environment variables. Nothing is read from a
config file, and no server contacts any central service.

### `servers/libvirt`

| Variable | Purpose |
|---|---|
| `MCP_SSH_KEY_PATH` | Private key used to reach remote hypervisors over SSH. Default `/root/.ssh/id_ed25519`. |
| `MCP_CREDENTIAL_KEY` | Fernet key used to encrypt guest credentials before they are stored. When unset, the clone tools **refuse to persist** a credential rather than writing it in plaintext. |
| `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` | Optional PostgreSQL inventory used to resolve a host's name from its address and back. Unset simply disables that lookup. |

### `servers/active_directory`

| Variable | Purpose |
|---|---|
| `AD_DC_HOST`, `AD_DC_USERNAME`, `AD_DC_PASSWORD`, `AD_DC_DOMAIN` | Register a domain controller at startup. All four must be set or the server starts with no DC and you register one at runtime with `add_dc`. |
| `AD_TLS_CA_BUNDLE` | CA bundle used to validate the DC's certificate. When set, certificate validation is **required**; when unset, LDAP still uses StartTLS but does not verify the peer. Set this in production. |
| `AD_ALLOW_CLEARTEXT_BIND` | `true` disables StartTLS entirely, sending the bind password unencrypted. Intended only for an isolated lab, and the server logs a warning on every connection. |

### `servers/winrm`

| Variable | Purpose |
|---|---|
| `WINRM_MCP_STAGING_ROOT` | Local directory used to stage files for upload/download. Default `/var/lib/mcp-winrm/staging`. |

Hosts are registered at runtime with `add_host`; credentials are never read from the environment.

### `servers/sql`

| Variable | Purpose |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` | Default connection used when a tool is called without an explicit alias. |
| `SQL_MCP_RO_USER`, `SQL_MCP_RO_PASSWORD` | A read-only role. Point the agent at this and the query tools cannot write. |
| `SQL_MCP_BACKUP_DIR` | Directory `backup_db` writes dumps to. Default `/var/backups`. |

`init_schema` creates a small self-contained inventory (`hosts`, `vms`, `networks`, `users`) —
it does not expect an existing schema.

### `servers/bash`

| Variable | Purpose |
|---|---|
| `BASH_MCP_ALLOWED_ROOTS` | Colon-separated allowlist of absolute directories the file tools may touch. |
| `BASH_MCP_ROOT` | Single directory used as the allowlist when `BASH_MCP_ALLOWED_ROOTS` is unset, and as the base for relative paths. |

The file tools fail closed. With neither variable set they confine themselves to the first
writable of `/var/lib/mcp/bash_mcp` or `/srv/mcp/bash_mcp` (falling back to a directory beside
the package), and every path is resolved through `realpath` and rejected if it escapes an allowed
root — so symlinks and `..` do not get you out. Set the allowlist to widen access deliberately,
not to become safe. This confines the **file** tools; the command-execution tools run whatever
you ask them to.

## Wiring into an MCP client

`examples/claude_desktop_config.json` is a complete starting point. Copy the blocks you want
into your client's config, replacing `/path/to/mcp-infrastructure-servers` with the real path.

```json
{
  "mcpServers": {
    "bash": {
      "command": "/path/to/mcp-infrastructure-servers/.venv/bin/python",
      "args": ["-m", "bash_mcp.server"],
      "env": {
        "PYTHONPATH": "/path/to/mcp-infrastructure-servers/servers/bash",
        "BASH_MCP_ALLOWED_ROOTS": "/srv/managed:/var/log"
      }
    }
  }
}
```

Two things matter here:

- **`PYTHONPATH` must point at the individual server directory** (`servers/bash`), never at
  `servers/`. Each server directory contains one importable package. Putting `servers/` on the
  path would let the `servers/winrm/` directory shadow the third-party `winrm` module that the
  WinRM server itself depends on.
- The libvirt server is launched by script path (`servers/libvirt/server.py`); the other four
  are launched as modules (`-m ad_mcp.server`, `-m winrm_mcp.server`, `-m sql_mcp.server`,
  `-m bash_mcp.server`).

To check a server outside a client, speak JSON-RPC to it directly:

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
 | PYTHONPATH=servers/bash .venv/bin/python -m bash_mcp.server
```

If you pipe input this way, the server may exit on EOF before flushing its reply. Keep stdin
open until the response arrives — a real client does this for you.

## Security

These servers hand an AI model the ability to run commands as root, reset domain passwords,
delete virtual machines and drop database rows. Treat each one as a privileged service.

- **Give each server its own least-privileged identity.** A dedicated SSH key restricted by
  `command=`/`from=` in `authorized_keys`; a PostgreSQL role with only the rights it needs
  (`SQL_MCP_RO_USER` exists for exactly this); a delegated AD account scoped to the OUs it
  manages rather than Domain Admin.
- **Widen the filesystem allowlist only as far as you need.** The file tools already fail closed
  to a managed default root; `BASH_MCP_ALLOWED_ROOTS` opens them up. The execution tools
  (`run_command`, `run_script`) are not path-confined at all — that is the gap the allowlist does
  not cover.
- **Do not disable transport security.** `AD_ALLOW_CLEARTEXT_BIND` sends a bind password in the
  clear. Set `AD_TLS_CA_BUNDLE` so the DC's certificate is actually verified.
- **Prefer HTTPS WinRM (5986) over HTTP (5985).** NTLM over plain HTTP exposes the exchange to
  anyone on the path.
- **Set `MCP_CREDENTIAL_KEY`** if you use the clone tools. Without it they decline to store
  guest credentials at all, which is the safe outcome but means the feature does nothing.
- **Keep credentials in the client's `env` block or a secret manager**, never in argv, where any
  local user can read them from the process table.
- **Run behind human approval for destructive tools.** Most clients can require confirmation per
  tool; `delete_vm`, `delete_object`, `reset_password`, `execute_statement`, `manage_service` and
  the file-deletion tools all deserve it.
- These servers perform **no authorization of their own**. Any client that can reach a server can
  call every tool it exposes. Isolation is the deployer's responsibility.

## What each is useful for

**libvirt** — driving a KVM fleet conversationally: provision from a golden image, clone across
hypervisors, snapshot before a risky change and roll back, or answer "which VMs are on this host
and what IPs do they have".

**active_directory** — onboarding and offboarding at the directory level: create a user in the
right OU with the right groups, reset a locked account, publish DNS records for new services, or
audit GPO links without opening a management console.

**winrm** — operating Windows hosts that have no SSH: read event logs while diagnosing a
failure, restart a stuck service, push a file and run it, or collect adapter and disk state
across a set of machines.

**sql** — letting an agent introspect and query a database safely: describe an unfamiliar table,
run a parameterised read against a read-only role, or maintain a small inventory that the other
servers' tools can resolve names against.

**bash** — the general-purpose fallback for Linux hosts, locally or over SSH: check disk
pressure, tail a log, install a package, restart a unit, or run a short script across a group of
machines.


## License

MIT — see [LICENSE](LICENSE).
