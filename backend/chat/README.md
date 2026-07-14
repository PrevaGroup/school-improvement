# chat — conversational surface (scaffold)

> **SCAFFOLD / MAP ONLY — no code has moved here yet.** This documents where the feature's code
> currently lives. Relocation is a later step (see `docs/MODULES.md`). Import from the paths below.

A conversational endpoint over the plan + peer marts (Long Beach prototype). It exposes tools to
the model — never invents data — and grounds every answer in mart output: how a school compares to
its demographically-similar peers, and what its plan funds for attendance.

## Component map (where the code is today)

| Concern | File(s) | Notes |
|---|---|---|
| Chat endpoint + tools | `backend/app/chat.py` | tools `find_similar_schools`, `compare_to_peers` (and attendance-plan lookup) |

The tools wrap **plan_marts** / **likeschools** serving functions currently imported from
`app.marts` (`fetch_like_schools`, `fetch_peer_benchmark`, `fetch_attendance_plans`).

## Contract

- **Owns:** no tables.
- **Reads:** the serving functions / endpoints of `plan_marts` and `likeschools`.
- **Serves:** `/chat`.

## Boundary

`chat` is the top of the stack — a pure consumer. Today it imports serving helpers directly from
`app.marts`; post-reorg it should call the modules' serving surfaces (their `api/` routers or
documented serving functions), so a change to a mart's internals doesn't reach into chat.
