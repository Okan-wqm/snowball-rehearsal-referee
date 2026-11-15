"""The seed's reference answer to `tohum/29v` (seed-053, E588): the policy paths a Stage 0 loop reads, with the value
it finds at each, as one JSON line. `python -m policy.reads <policy.json>` from `referee/`.

Each path is written whole, its section first (`26b`); a path the file lacks is `null`, never a value found elsewhere.
"""

import json
import sys

READS = (  # the Stage 0 loop's reads, each where `18a` writes it
    "constitutional.stage_budgets.asama_0.canary_usd",  # llm.call
    "constitutional.security_keywords",  # profile.derive
    "constitutional.license_allowlist",  # deps.fetch
    "constitutional.license_exceptions",  # deps.fetch
    "operating.unit_inputs_bytes", "operating.deps_bytes", "operating.worktree_bytes",
    "operating.container_mem_bytes", "operating.kos_wall_s", "operating.test_total_s", "operating.output_bytes",
)


def value_at(policy, path):
    node = policy
    for key in path.split("."):
        if not (isinstance(node, dict) and key in node):
            return None
        node = node[key]
    return node


def main(argv):
    with open(argv[1], encoding="utf-8") as fh:
        policy = json.load(fh)
    print(json.dumps({path: value_at(policy, path) for path in READS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
