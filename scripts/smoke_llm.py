# LEARN[06]: host.docker.internal vs localhost from containers (for a Docker Desktop/WSL2 user)
# Why this way: the plan (D4) runs Ollama on the *host* and has containerized services reach it
#   through the magic DNS name host.docker.internal:11434, not localhost:11434. Inside a container
#   "localhost" is the container itself, so pointing at it is never going to reach the host.
#   Compose wiring uses extra_hosts: ["host.docker.internal:host-gateway"] to make that name resolve
#   to the host's loopback on Docker Desktop / WSL2.
# Good sides:
#   - one stable name works across Docker Desktop (Mac/Windows) and Docker on WSL2
#   - no need to know the host's dynamic IP; it is resolved by the daemon at container start
# Drawbacks:
#   - host.docker.internal is not the same on bare Linux hosts (the host-gateway mapping must be
#     declared); it is a Docker Desktop/WSL2 convenience, not a portability guarantee
#   - only host services bound to 0.0.0.0 are reachable; a service bound to 127.0.0.1 on the host
#     will NOT be visible from a container even via host-gateway (hence OLLAMA_HOST=0.0.0.0)
#   - it leaks host network topology into config, which is a demo-only convenience (see L2 posture)
# Concept: Docker runs each container in a network namespace, a private view of the network stack:
#   its own loopback and routing. So localhost inside a container is the container. To reach a
#   process on the host you must traverse the namespace boundary. Docker Desktop/WSL2 provides the
#   DNS name host.docker.internal that resolves to the host (via a gateway that Docker Desktop sets
#   up), and "host-gateway" is the compose extra_hosts value that maps that name to the host's
#   gateway address. Two subtle points that trip people up: (1) the host process must bind to
#   0.0.0.0 (all interfaces), because a host-bound-to-loopback service is inside the host's own
#   namespace and not exported; and (2) localhost/127.0.0.1 from *within* a container is never the
#   host, regardless of how it looks. On a plain Linux host that "just works" because processes
#   share one namespace; the failure is specific to the namespace isolation Docker Desktop/WSL2
#   imposes. A Java reader should think of it as the difference between calling a service on the
#   same JVM loopback versus calling it across a network hop.
# See also: the D4 design decision in PLAN.md, LEARN[05] (OpenAI-compatible client)
from __future__ import annotations

import argparse
import sys

from pydantic import BaseModel

from sentinel.config import Settings
from sentinel.llm.factory import get_chat_model
from sentinel.llm.structured import StructuredOutputError, structured_call


class HealthCheck(BaseModel):
    """Minimal schema for the smoke test — deliberately small so a local model can satisfy it."""

    ok: bool
    echo: str


SMOKE_INSTRUCTION = (
    "You are a health check for the Sentinel smoke test. Respond with a single JSON object with "
    "the fields: ok (boolean, always true) and echo (a string, exactly 'pong')."
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the configured LLM provider through the structured-output loop."
    )
    parser.add_argument(
        "--provider",
        choices=["openai", "ollama"],
        default=None,
        help="Override the configured provider (equivalent to setting LLM_PROVIDER).",
    )
    args = parser.parse_args()

    settings = Settings()
    if args.provider:
        settings.llm.provider = args.provider

    model = get_chat_model(settings)
    endpoint = settings.llm.base_url

    print(f"Sentinel smoke test -> provider={settings.llm.provider} model={settings.llm.model}")
    print(f"  endpoint: {endpoint}")

    try:
        result = structured_call(model, SMOKE_INSTRUCTION, HealthCheck)
    except StructuredOutputError as exc:
        print(
            f"FAIL: model reached but produced no valid structured output.\n  {exc}",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - a smoke test must report any connection/transport error
        print(
            f"FAIL: could not reach the LLM endpoint at {endpoint!r} "
            f"(provider={settings.llm.provider}).\n"
            f"  {type(exc).__name__}: {exc}\n"
            "  Check that the service is running and reachable (e.g. ollama serve with "
            "OLLAMA_HOST=0.0.0.0; see README).",
            file=sys.stderr,
        )
        return 2

    print(f"PASS: got structured output -> {result.model_dump()}")
    if result.ok and result.echo == "pong":
        return 0
    print("FAIL: returned object did not match the expected health-check payload.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
