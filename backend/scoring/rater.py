"""The rater: the model call, and the identity that call is stamped with.

Two things live here and they are deliberately the same object's concern.

THE IDENTITY. `RaterIdentity` holds exactly the columns of `registry_scoring_configuration` that
determine what a score means — model id, effort, prompt fingerprint, span-verifier normalization
version. Not "the model we used" plus four other facts reassembled afterwards: one identity, which
`score_event.scoring_configuration_id` points at. A rater facet in a many-facet model has to be a
thing before its severity can be estimated, and this is that thing.

`model_id` is pinned exactly and an alias is refused. A floating alias that quietly resolves to a
new build is precisely the silent rater change the freeze exists to prevent, and it does not
announce itself: every score before and after looks identical, and the severity shift shows up as
students appearing to get worse.

There are no sampling parameters. Current models removed them — `temperature=0` returns a 400 —
so `effort` is what "decoding parameters" means in practice, and it is stamped like one.

THE CALL. `Rater` is a protocol with two methods, so `score.py` can be tested against a scripted
fake without a network, an API key, or a dollar. `AnthropicRater` is the real one. Nothing above
this file knows which it has.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from .prompts import (EVIDENCE_SCHEMA, SCORE_SCHEMA)

SECRET_NAME = "anthropic-api-key"

# A tag is a moving target. Pinning means pinning.
_ALIASES = ("latest", "-latest")


@dataclass(frozen=True)
class Usage:
    """What a call cost, so a run can report it and a budget can stop it."""
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.calls + other.calls,
                     self.input_tokens + other.input_tokens,
                     self.output_tokens + other.output_tokens)


@dataclass(frozen=True)
class RaterIdentity:
    """One rater, as the configuration row records it.

    `config_id` is the identifier a score_event points at. `definition_hash` is computed from the
    parts, so two configurations that describe the same rater hash the same and a configuration
    whose parts were edited in place stops matching its own hash.
    """
    config_id: str
    model_id: str
    effort: str | None
    prompt_versions: dict
    normalization_version: str

    def __post_init__(self) -> None:
        if any(a in self.model_id for a in _ALIASES):
            raise ValueError(
                f"model_id {self.model_id!r} looks like a floating alias. A configuration is a "
                f"rater; an alias that resolves to a new build changes the rater without changing "
                f"the record, which is the one failure the freeze exists to prevent.")

    @property
    def definition_hash(self) -> str:
        return hashlib.sha256(
            json.dumps({"model_id": self.model_id, "effort": self.effort,
                        "prompt_versions": self.prompt_versions,
                        "normalization_version": self.normalization_version},
                       sort_keys=True, separators=(",", ":")).encode("utf8")
        ).hexdigest()[:32]


class Rater(Protocol):
    """What `score.py` needs. Two calls, in this order, never merged."""

    identity: RaterIdentity

    def propose_spans(self, prompt: str) -> tuple[list[str], Usage]: ...

    def assign_level(self, prompt: str) -> tuple[dict, Usage]: ...


class AnthropicRater:
    """The real rater.

    One `messages.create` per stage per criterion. Not batched across criteria and not batched
    across students: batching either one is what the separation is for, and an API convenience is
    not a reason to give it up.
    """

    def __init__(self, identity: RaterIdentity, *, api_key: str | None = None,
                 max_tokens: int = 16000, max_retries: int = 5) -> None:
        import anthropic

        self.identity = identity
        self._max_tokens = max_tokens
        self._client = anthropic.Anthropic(api_key=api_key or resolve_api_key(),
                                           max_retries=max_retries)

    def propose_spans(self, prompt: str) -> tuple[list[str], Usage]:
        out, usage = self._call(prompt, EVIDENCE_SCHEMA)
        return list(out["spans"]), usage

    def assign_level(self, prompt: str) -> tuple[dict, Usage]:
        return self._call(prompt, SCORE_SCHEMA)

    def _call(self, prompt: str, schema: dict) -> tuple[dict, Usage]:
        r = self._client.messages.create(
            model=self.identity.model_id,
            max_tokens=self._max_tokens,
            output_config={"effort": self.identity.effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
        text = next(b.text for b in r.content if b.type == "text")
        return json.loads(text), Usage(1, r.usage.input_tokens, r.usage.output_tokens)


def resolve_api_key(project: str | None = None) -> str:
    """Env, then core's settings, then a gcloud shell-out. Never a file, never a literal.

    The middle one is the path that matters — `app.config` already resolves and caches this secret
    for the rest of the system, and a second mechanism reading the same secret differently is how
    two halves of a deployment end up on two keys. The shell-out stays as the last resort because
    it is what makes the pipeline runnable from a workstation with nothing configured but gcloud,
    which is where a prompt change actually gets tried.

    `gcloud` on Windows is `gcloud.cmd`; `CreateProcess` will not find the bare name, which is why
    both are tried rather than going through a shell.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        from app.config import settings

        if key := settings.anthropic_api_key_value:
            return key
    except Exception:                     # no settings, no secret access — fall through to gcloud
        pass
    gc = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not gc:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is unset and gcloud is not on PATH — cannot reach Secret Manager.")
    cmd = [gc, "secrets", "versions", "access", "latest", f"--secret={SECRET_NAME}"]
    if project:
        cmd.append(f"--project={project}")
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
