# BWI Federated User Directory (experimental)

> Status: **experimental**, disabled by default. All configuration lives under
> `experimental_features` and is prefixed `bwi_federated_user_dir_*`.

## 1. Motivation

By default a Synapse user directory search only returns:

- local users, and
- remote users that the local server has *already encountered* (because they
  share a room with a local user).

This means users on other federated homeservers are effectively invisible to
local searches until someone shares a room with them.

This feature lets a homeserver **periodically pull user directory entries from
other known homeservers** and cache them locally, so that a normal client-side
user directory search (`POST /_matrix/client/v3/user_directory/search`) returns
those remote users **natively** — without any per-search federation traffic.

### Design constraints

- The client-facing search stays a pure **local database query**. We never do
  live federation calls per search (that could be slow and could return huge
  result sets and metadata).
- Federation concerns (which servers to contact, timing, wire format) are kept
  out of the user directory. The user directory only receives already-parsed,
  neutral user records.

## 2. High-level architecture

There are two clearly separated responsibilities:

```
                 periodic (background task)
                 ┌───────────────────────────────────────────┐
                 │ FederationClient._sync_federated_user_dir   │
                 │  1. get_known_destinations()  (from DB)     │
                 │  2. for each dest:                          │
                 │       user_directory_search() over fed.     │
                 │  3. parse -> [RemoteUserDirectoryEntry]     │
                 └───────────────┬─────────────────────────────┘
                                 │ upsert_remote_users(entries)
                                 ▼
                 ┌───────────────────────────────────────────┐
                 │ UserDirectoryFederationHandler              │
                 │  - filters out our own users                │
                 │  - store.upsert_federated_remote_users()    │
                 └───────────────┬─────────────────────────────┘
                                 ▼
                 ┌───────────────────────────────────────────┐
                 │ user_directory / user_directory_search /    │
                 │ users_in_public_rooms  (local DB tables)    │
                 └───────────────────────────────────────────┘

  client search  ──►  store.search_user_dir()  ──►  reads the same local tables
```

- **Producer side (federation):** `FederationClient` runs the periodic job,
  talks to remote servers and produces neutral `RemoteUserDirectoryEntry`
  objects.
- **Consumer side (user directory):** `UserDirectoryFederationHandler` persists
  those entries into the existing user directory tables. This subclass is only
  instantiated when the feature is enabled (`get_user_directory_handler()`);
  with the feature off, the plain `UserDirectoryHandler` is used and nothing
  federation-related is loaded.
- **Responder side (federation):** when the feature is enabled, the server
  exposes a federation endpoint that answers user directory search requests with
  its **own local** users.

## 3. Data flow in detail

### 3.1 The periodic sync job (producer)

`FederationClient._sync_federated_user_directory()` is decorated with
`@wrap_as_background_process("federated_user_directory_sync")` and scheduled via
`looping_call` in `FederationClient.__init__`, gated on:

```python
hs.config.experimental.bwi_federated_user_dir_enabled
and hs.config.worker.run_background_tasks
```

Each run:

1. `destinations = await self.store.get_known_destinations()` — reads **all rows
   from the `destinations` table** (servers we already know about). Destinations
   are **not** configured; they come from the DB.
2. Skips our own server (`_is_mine_server_name`).
3. For every destination, calls
   `user_directory_search(requester, destination, timeout, limit)`, which fetches
   the remote server's full local directory. The synthetic requester is
   `@_user_directory_sync:<our_server_name>` (the remote endpoint requires the
   requester to belong to the origin server).
4. Parses each response with `_parse_remote_user_directory_results()` into
   `RemoteUserDirectoryEntry` objects (skipping malformed rows), de-duplicated
   by `user_id`.
5. Hands the list to `hs.get_user_directory_handler().upsert_remote_users(...)`.

Errors per destination are swallowed (the federation client returns
`{"limited": False, "results": []}` on failure), so one unreachable server does
not break the whole sync.

### 3.2 Persisting remote users (consumer)

`UserDirectoryFederationHandler.upsert_remote_users(users)`:

- No-op unless `self.update_user_directory` is true (only the worker that owns
  the user directory writes to it).
- Drops any entry where `is_mine_id(user_id)` is true (defensive — never store
  our own users as if they were remote).
- Calls `store.upsert_federated_remote_users(cache_room_id, profiles)`.

`store.upsert_federated_remote_users()` does, in **one transaction**:

1. `_update_profiles_in_user_dir_txn(...)`:
   - upsert into **`user_directory`** (`display_name`, `avatar_url`),
   - clear any stale flag in `user_directory_stale_remote_users`,
   - upsert the search vector into **`user_directory_search`**
     (Postgres `tsvector` / SQLite text).
2. upsert `(user_id, cache_room_id)` into **`users_in_public_rooms`**.

### 3.3 The sentinel cache room

`search_user_dir` only returns a user (when `search_all_users` is off) if they
share a private room with the searcher **or** appear in `users_in_public_rooms`.
Remote users we cache share no room with anyone locally, so we mark them as
visible by inserting them into `users_in_public_rooms` against a **synthetic
room id**:

```
!bwi-fed-user-dir-cache:<our_server_name>
```

This room does **not exist** (no events, no membership, no state). It only
re-uses the existing visibility mechanism. Defined in
`synapse/handlers/user_directory.py`:

```python
FEDERATED_USER_DIR_CACHE_ROOM_LOCALPART = "bwi-fed-user-dir-cache"

def federated_user_dir_cache_room_id(server_name: str) -> str:
    return f"!{FEDERATED_USER_DIR_CACHE_ROOM_LOCALPART}:{server_name}"
```

All cached federated users can be listed or purged via this id, e.g.:

```sql
SELECT user_id FROM users_in_public_rooms
WHERE room_id LIKE '!bwi-fed-user-dir-cache:%';
```

### 3.4 The responder endpoint

A server answers user directory searches from other servers via a federation
servlet (`FederationUserDirectorySearchServlet`). This servlet is **only
registered when `bwi_federated_user_dir_enabled` is true** — see
`synapse/federation/transport/server/__init__.py`. If the feature is disabled,
the endpoint is not exposed at all and returns `404 M_UNRECOGNIZED`.

```
POST /_matrix/federation/unstable/org.matrix.bwi_federated_user_dir/user_directory/search
```

Request body:

```json
{ "requester": "@user:origin.example", "limit": 10 }
```

Server behaviour (`FederationServer.on_user_directory_search_request`):

- Requires `requester` to belong to the calling `origin` (else `400`).
- `limit` is clamped to `[0, 50]`.
- Returns **all** of this server's own searchable users (`is_mine_id`); the
  endpoint always syncs the full local directory rather than matching a term.

## 4. Configuration reference

All keys are under `experimental_features`:

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `bwi_federated_user_dir_enabled` | bool | `false` | Master switch. Does **two** things: (a) schedules the periodic sync job (on the background-tasks worker, the *consumer* role), and (b) exposes the federation responder endpoint so other servers can query this server's users (the *source* role). A server that leaves this off is neither queried nor queries others. |
| `bwi_federated_user_dir_sync_limit` | int | `50` | Max results requested per destination. Must be `≥ 1`. |
| `bwi_federated_user_dir_sync_interval` | duration | `"4h"` | How often the sync runs (e.g. `"30s"`, `"15m"`, `"4h"`). Parsed to ms; must be positive. |
| `bwi_federated_user_dir_federation_search_timeout` | int (ms) | `2000` | Per-request federation timeout for the outgoing search. |

> Note: the list of remote servers to query is **not** configured. It is taken
> from the `destinations` table (servers this homeserver already federates
> with). See operational notes below.

### Example

```yaml
experimental_features:
  bwi_federated_user_dir_enabled: true
  bwi_federated_user_dir_sync_interval: "30s"
  bwi_federated_user_dir_sync_limit: 50
  bwi_federated_user_dir_federation_search_timeout: 5000
```

Validation happens at startup in `synapse/config/experimental.py`; a misconfig
(e.g. enabled with a non-positive interval or limit) raises a
`ConfigError` and the server refuses to start.

## 5. Operational notes

- **Where it runs:** the sync job runs only where
  `worker.run_background_tasks` is true. In a monolith that is the main process;
  in a worker deployment it is the designated background-tasks worker. Writes to
  the directory additionally require this process to own the user directory
  (`update_user_directory_from_worker`).
- **Both ends must opt in:** the responder endpoint is only registered when the
  flag is enabled. So for server A to pull users from server B, **B** must also
  have `bwi_federated_user_dir_enabled: true` (otherwise B returns
  `404 M_UNRECOGNIZED`). Enable the flag on every server that should participate.
- **Destinations bootstrap:** if the `destinations` table is empty (a fresh
  server that has not federated yet), the sync has nothing to query and does
  nothing. Destinations get populated organically once the server federates
  (e.g. a local user joins/invites across servers).
- **First run timing:** `looping_call` waits one full interval before the first
  run (there is no immediate run on startup).
- **Idempotency:** re-running the sync upserts the same rows; there are no
  duplicates.
- **Search visibility on the consumer:** cached remote users are returned by the
  normal client search because of the sentinel cache room (section 3.3),
  regardless of the `user_directory.search_all_users` setting.

## 6. Components changed / added

| File | Change |
| --- | --- |
| `synapse/types/__init__.py` | New boundary type `RemoteUserDirectoryEntry` (`user_id`, `display_name`, `avatar_url`). |
| `synapse/config/experimental.py` | New `bwi_federated_user_dir_*` config keys + validation. |
| `synapse/federation/federation_client.py` | `looping_call` scheduling, `_sync_federated_user_directory()` background job, `_parse_remote_user_directory_results()`, synthetic requester constant. |
| `synapse/storage/databases/main/transactions.py` | New `get_known_destinations()` helper. |
| `synapse/storage/databases/main/user_directory.py` | New `upsert_federated_remote_users()` storing profiles + search index + sentinel visibility. |
| `synapse/handlers/user_directory.py` | New `UserDirectoryFederationHandler(UserDirectoryHandler)` with `upsert_remote_users()`; sentinel cache-room helpers. |
| `synapse/server.py` | `get_user_directory_handler()` returns `UserDirectoryFederationHandler` **only when the feature is enabled**, otherwise the plain `UserDirectoryHandler`. |
| `synapse/federation/transport/server/federation.py` | Responder servlet `FederationUserDirectorySearchServlet`. |
| `synapse/federation/transport/server/__init__.py` | Gates registration of the responder servlet behind `bwi_federated_user_dir_enabled`. |
| `synapse/federation/transport/client.py` | Client transport `user_directory_search()`. |
| `synapse/federation/federation_server.py` | `on_user_directory_search_request()` (local-only filtered results). |

Tests:

- `tests/handlers/test_user_directory.py::FederatedUserDirectoryHandlerTestCase`
  — upsert persists profiles + visibility, ignores local users, search returns
  cached remote users.
- `tests/federation/test_federation_client.py::FederatedUserDirectorySyncTestCase`
  — sync reads destinations from the DB and upserts; skips our own server.

## 7. Trying it out (3-server demo)

The repo ships a 3-homeserver demo (`demo/start.sh`, ports 8080/8081/8082).

1. Add the `experimental_features` block (section 4) to each
   `demo/<port>/<port>.config`.
2. Restart: `./demo/stop.sh && ./demo/start.sh --no-rate-limit`.
3. Run the helper: `./demo/test_fed_user_dir_sync.sh`.

The helper registers "target" users that join no room (so they can only become
searchable via the sync), seeds the `destinations` table directly via `sqlite3`,
waits for a sync cycle, and verifies the cached remote users appear in each
server's client-side search. To probe the raw responder endpoint in isolation,
use `demo/fed_user_directory_search.py`.

## 8. Limitations & caveats

- **Sentinel room is a deliberate hack.** We reuse `users_in_public_rooms` with
  a non-existent room id. Any tooling that assumes rows there reference real
  rooms must ignore the `!bwi-fed-user-dir-cache:*` id.
- **No automatic eviction.** Cached entries are upserted but not pruned when a
  remote user is removed/renamed on the source server; they are refreshed on the
  next sync but stale users are not deleted. (Future work.)
- **Discovery pulls the full remote directory.** Each sync fetches all of a
  remote server's searchable local users (subject to `..._sync_limit`), rather
  than matching configured search terms.
- **Destinations come from the DB**, so a server only syncs from homeservers it
  already knows about.
