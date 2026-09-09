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
import threading
from dataclasses import dataclass, field
from typing import Protocol

from .prompts import (BAND_SCHEMA, EVIDENCE_SCHEMA, FEEDBACK_SCHEMA, FIT_SCHEMA,
                      SCORE_SCHEMA)

SECRET_NAME = "anthropic-api-key"

# A tag is a moving target. Pinning means pinning.
_ALIASES = ("latest", "-latest")

# The four places this system calls a model. Named rather than inferred, so a configuration cannot
# assign a model to a stage that does not exist and discover it at run time.
#
# They are the keys `prompts.fingerprint()` already uses, deliberately: the prompt for a stage and
# the model that reads it are two halves of the same choice, and having them keyed differently is
# how a config ends up overriding a stage whose prompt it never saw.
STAGES = ("fit", "evidence", "score", "band", "feedback")

# How stage D produces a band. See `RaterIdentity.level_method`.
LEVEL_METHODS = ("category", "cumulative")


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
    # The RESOLVED escalation policy, as `escalate.Policy.as_dict()` — how deep this rater is
    # allowed to look.
    #
    # Migration 0027 deliberately left this out and wrote the counter-argument down rather than
    # winning it: escalation decides how many chances a criterion gets to produce a score, which
    # is adjacent to what a score MEANS rather than the same thing, and the per-event stamps
    # (`scrutiny_passes`, `escalation_trigger`, the escalated `effort`) already make what happened
    # recoverable row by row. The cost of including it — raising a budget re-rates every paper
    # ever scored — was judged too big to decide quietly inside a migration.
    #
    # It is included now because that deferred decision has been made: the HARNESS is the rater.
    # Two configurations differing only in budget produce different bodies of scores, so they are
    # different raters, and a measurement system that hashes them the same averages them together
    # as one.
    #
    # RESOLVED rather than the raw column, so a NULL escalation and one spelling out the defaults
    # hash identically. They are the same rater; only one of them says so out loud.
    #
    # Required, with no default. A default would let a construction site stay silent about part of
    # the rater it is defining, which is the thing this field exists to stop.
    escalation: dict
    # Per-stage model overrides, e.g. {"evidence": "claude-haiku-4-5-20251001"}. Absent stages use
    # `model_id`.
    #
    # WHY THIS IS WORTH HAVING. Stage C proposes spans and every span it proposes is then verified
    # as an exact substring of the paper — so a weaker model's failure there is caught
    # mechanically and costs verified spans rather than producing a wrong score. Stage D assigns a
    # level and NOTHING downstream checks it. Those are different risks and they do not deserve
    # the same model. Stage C also carries the whole essay in its prompt, once per trait, which is
    # where the input tokens actually are.
    #
    # WHY IT IS AN OVERRIDE MAP AND NOT A REQUIRED FOUR. So `model_id` stays the answer to "what
    # model is this", and a single-model rater does not have to say the same string four times.
    # The RESOLVED map is what gets hashed, so declaring nothing and declaring the same model
    # everywhere are the same rater — the same reasoning as the escalation policy above.
    stage_models: dict | None = None
    # How stage D turns evidence into a band.
    #
    #   "category"   — one call naming a band. What every score before this used.
    #   "cumulative" — one call per band asking whether the writing meets or exceeds it, with the
    #                  band computed from the answers.
    #
    # Part of the identity because it is the largest single difference between two raters this
    # system can express. On the first anchor wave the category form used 17% of the scale the
    # humans used and awarded no 6s at all across 334 papers; the span diagnostic then showed the
    # evidence was not the limit. Two configurations differing only in this produce entirely
    # different bodies of scores.
    #
    # Defaults, unlike `escalation`, because there is no ambiguity to resolve: an unspecified
    # method IS the category form, which is what every existing configuration ran.
    level_method: str = "category"
    # The probability a band must clear. Meaningless under "category" and hashed anyway — a rater
    # is its parameters, and pretending a field is absent because the current method ignores it is
    # how a hash stops describing a rater when the method changes.
    level_threshold: float = 0.5

    @property
    def models(self) -> dict:
        """The resolved model per stage. This, not `model_id`, is what actually gets called."""
        return {stage: (self.stage_models or {}).get(stage) or self.model_id
                for stage in STAGES}

    def __post_init__(self) -> None:
        if self.level_method not in LEVEL_METHODS:
            raise ValueError(
                f"unknown level_method {self.level_method!r}; the methods are "
                f"{list(LEVEL_METHODS)}.")
        if not 0 < self.level_threshold < 1:
            raise ValueError(
                f"level_threshold {self.level_threshold!r} is not a probability strictly between "
                f"0 and 1. At 0 every band clears and every paper is a 6; at 1 none does and "
                f"every paper is a 1.")
        unknown = set(self.stage_models or {}) - set(STAGES)
        if unknown:
            raise ValueError(
                f"unknown scoring stage(s) {sorted(unknown)} in stage_models. The stages are "
                f"{list(STAGES)}; a model assigned to a stage that does not exist is a model that "
                f"never gets used, and nothing would say so.")
        # EVERY resolved model, not just `model_id` — an override is exactly as capable of being
        # a floating alias, and it is the one nobody would think to check.
        for stage, model in self.models.items():
            if any(a in model for a in _ALIASES):
                raise ValueError(
                    f"model {model!r} for stage {stage!r} looks like a floating alias. A "
                    f"configuration is a rater; an alias that resolves to a new build changes the "
                    f"rater without changing the record, which is the one failure the freeze "
                    f"exists to prevent.")

    @property
    def definition_hash(self) -> str:
        return hashlib.sha256(
            # `models`, not `model_id`: the resolved per-stage map is what was actually called.
            # A rater declaring one model and a rater declaring that same model at every stage are
            # the same rater and must collide.
            json.dumps({"models": self.models, "effort": self.effort,
                        "prompt_versions": self.prompt_versions,
                        "normalization_version": self.normalization_version,
                        "escalation": self.escalation,
                        "level_method": self.level_method,
                        "level_threshold": self.level_threshold},
                       sort_keys=True, separators=(",", ":")).encode("utf8")
        ).hexdigest()[:32]


class Rater(Protocol):
    """What `score.py` needs. Two calls, in this order, never merged."""

    identity: RaterIdentity

    # Stage B, before either of the scoring calls. Named like the others rather than folded into a
    # generic call so a fake rater cannot answer the wrong stage by accident — the fit gate is the
    # one stage where a wrong answer removes a student instead of misplacing them.
    def judge_fit(self, prompt: str) -> tuple[dict, Usage]: ...

    # Returns (spans, present, usage). `present` is whether the criterion describes
    # anything the writing actually contains — a counterclaim in an essay that argues one
    # side has none. Returned rather than inferred from an empty span list, because the
    # model returned spans anyway: a nearby passage that IS in the paper, so verification
    # passed and a missing element got a quality score.
    def propose_spans(self, prompt: str) -> tuple[list[str], bool, Usage]: ...

    def assign_level(self, prompt: str) -> tuple[dict, Usage]: ...

    # Stage D, cumulative form: the probability that the writing meets or exceeds ONE band.
    # Separate from `assign_level` rather than a mode of it, so a fake rater has to be explicit
    # about which stage-D question it is answering and cannot satisfy a test by accident.
    def judge_band(self, prompt: str) -> tuple[dict, Usage]: ...

    # Stage E. Named rather than folded into a generic call so a fake rater has to be explicit
    # about which stage it is answering, and a test cannot accidentally answer the wrong one.
    def write_feedback(self, prompt: str) -> tuple[dict, Usage]: ...


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
        self._api_key = api_key or resolve_api_key()
        self._max_retries = max_retries
        # ONE CLIENT PER THREAD, not one per rater.
        #
        # Sharing a client across the scoring pools produced `400 Invalid request data` on about
        # one call in six under concurrency — reproduced with an IDENTICAL prompt: six sequential
        # calls all succeeded, six concurrent ones did not. The prompt was never the problem, and
        # a whole evening of the failure looking data-shaped came from that.
        #
        # It surfaced with the cumulative method because that nests two pools — criteria, and the
        # bands within each — so a paper has up to nineteen calls in flight instead of eight. The
        # category wave ran clean at the lower number, which is the worst way for a race to
        # behave: absent right up until the load that matters.
        #
        # Thread-local rather than per-call, so a thread reuses its connection pool. The lazy
        # property is what makes it work with a pool that creates threads after the rater exists.
        self._local = threading.local()

    @property
    def _client(self):
        client = getattr(self._local, "client", None)
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=self._api_key, max_retries=self._max_retries)
            self._local.client = client
        return client

    def judge_fit(self, prompt: str) -> tuple[dict, Usage]:
        return self._call(prompt, FIT_SCHEMA, "fit")

    def propose_spans(self, prompt: str) -> tuple[list[str], bool, Usage]:
        out, usage = self._call(prompt, EVIDENCE_SCHEMA, "evidence")
        # Defaulting to present: a rater that does not answer the question has not said the
        # writing lacks the element, and treating silence as absence would abstain on everything.
        return list(out["spans"]), bool(out.get("present", True)), usage

    def assign_level(self, prompt: str) -> tuple[dict, Usage]:
        return self._call(prompt, SCORE_SCHEMA, "score")

    def judge_band(self, prompt: str) -> tuple[dict, Usage]:
        return self._call(prompt, BAND_SCHEMA, "band")

    def write_feedback(self, prompt: str) -> tuple[dict, Usage]:
        return self._call(prompt, FEEDBACK_SCHEMA, "feedback")

    def _call(self, prompt: str, schema: dict, stage: str) -> tuple[dict, Usage]:
        # The stage is passed rather than inferred from the schema. A schema is a shape and two
        # stages could share one; the stage is the thing a configuration assigns a model to.
        r = self._client.messages.create(
            model=self.identity.models[stage],
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
