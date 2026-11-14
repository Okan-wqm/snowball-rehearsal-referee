"""The target branches the system keeps (tohum/01, asama-0/00 "Veri iki hedefin ``brain/state`` dalında, çalışma dalı
``brain/integration``"): the one place their names are written. Read by ``loop.job`` (D1's heads), ``ledger.append``
(the state writer), ``ledger.schema`` and ``activate``. Also the paths, in ``brain/state``'s commit, of its chained
files (tohum/01b: ``chain/*`` and ``ledger.jsonl`` are append only; tohum/26, tohum/27a), written by
``ledger.append`` and ``ledger.anchor`` and read by ``loop.state`` (D1's ``verify --previous`` and its root check),
of its ``status.md`` (asama-0/14 row 16), written by ``status.block`` and carried by D1 to D6 (``loop.pulled``), and
of the Sigstore bundle of a root (``state_bundle``; written by ``ledger.cycle``).

**The state directory** (``STATE_ROOT``; tohum/01a ``<state_root>``, tohum/26d "Yer"): every file of ``brain/state``
is under the one directory ``.brain/`` at the root of the commit, where the operator's ``stage-open`` reads
``.brain/ledger.jsonl``, ``.brain/chain/root.jsonl`` and the last root's bundle ``.brain/chain/<root>.sigstore.json``.
The directory is written here and nowhere else: a path of the commit is one of the constants below or
``state_bundle``'s; ``state_name`` is the file's name under the directory, for a place that carries a state file
outside a commit (``loop.pulled``'s artifact, whose ``state/`` holds no hidden directory).

``CHECK`` is the name of the check run the referee writes on a candidate's head before merging it into
``brain/integration`` (``target.land``, called by ``activate`` and D6 of ``yaz``): tohum/25a row 3's required
check of ``brain/integration``'s ruleset, "adı ``snowball-gate``".
"""

STATE = "brain/state"
INTEGRATION = "brain/integration"

STATE_ROOT = ".brain"
STATE_LEDGER = STATE_ROOT + "/ledger.jsonl"
STATE_ROOTS = STATE_ROOT + "/chain/root.jsonl"
STATE_CHAINS = (STATE_LEDGER, STATE_ROOTS)
STATE_STATUS = STATE_ROOT + "/status.md"


def state_bundle(root: str) -> str:
    """The path of the Sigstore bundle of the root ``root`` (64 hex): beside the root rows (tohum/26d "Yer")."""
    return "%s/chain/%s.sigstore.json" % (STATE_ROOT, root)


def state_name(path: str) -> str:
    """``path``'s name under the state directory; ``ValueError`` for a path that is not under it."""
    prefix = STATE_ROOT + "/"
    if not path.startswith(prefix) or len(path) == len(prefix):
        raise ValueError("%r is not under %s" % (path, prefix))
    return path[len(prefix):]

CHECK = "snowball-gate"
