"""Tests for scripts/check-hook-contract (the hooks-read-cwd-from-stdin lint).

See bento-k0p and the AGENTS.md rule: hook scripts must read the working
directory from the payload `cwd` field, not from `$PWD` or the process CWD.
"""

import importlib.machinery
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-hook-contract"


def _load_checker():
    loader = importlib.machinery.SourceFileLoader("check_hook_contract", str(SCRIPT))
    spec = importlib.util.spec_from_loader("check_hook_contract", loader)
    if spec is None:
        raise RuntimeError("unable to create spec for check-hook-contract")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


checker = _load_checker()
FAKE = Path("fake/hook.py")
FAKE_SH = Path("fake/hook.sh")


def _messages(findings) -> str:
    return "\n".join(f.message for f in findings)


class RealHooksComplyTest(unittest.TestCase):
    """The lint must pass on the committed hooks (integration guard)."""

    def test_script_exits_zero_on_repo(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(REPO_ROOT)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            result.returncode,
            0,
            f"check-hook-contract failed on committed hooks:\n{result.stderr}",
        )

    def test_decoy_filtering_does_not_erase_genuine_payload_reads(self) -> None:
        """Guard against the fix vacuously passing by rejecting every Python
        hook's `cwd` read: exactly the same 8 of 18 catalog Python hooks that
        reference the payload `cwd` field before the Subscript-recursion and
        temp-variable fixes must still reference it after."""
        import ast

        scripts = checker.find_hook_scripts(REPO_ROOT)
        py_scripts = [p for p in scripts if p.suffix == ".py"]
        self.assertEqual(len(py_scripts), 18)
        referencing = sum(
            1
            for p in py_scripts
            if checker._references_payload_cwd_ast(ast.parse(p.read_text()))
        )
        self.assertEqual(referencing, 8)

    def test_finds_the_hook_scripts(self) -> None:
        scripts = checker.find_hook_scripts(REPO_ROOT)
        self.assertTrue(scripts, "expected to discover hook scripts under catalog/hooks")
        names = {p.name for p in scripts}
        self.assertIn("ensure-worktree-permissions.py", names)
        self.assertIn("require-worktree.sh", names)


class PythonCheckTest(unittest.TestCase):
    def test_flags_unannotated_getcwd(self) -> None:
        src = "import os\n\n\ndef f(payload):\n    return payload.get('cwd') or os.getcwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("os.getcwd()" in m for m in _messages(findings).splitlines()))
        self.assertTrue(any("annotation" in f.message for f in findings))

    def test_flags_unannotated_path_cwd(self) -> None:
        src = "from pathlib import Path\n\n\ndef f(payload):\n    d = payload.get('cwd')\n    return d or Path.cwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("Path.cwd()" in f.message for f in findings))

    def test_same_line_annotation_suppresses(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    return payload.get('cwd') or os.getcwd()  # hook-cwd-exempt: fallback\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_multiline_annotation_above_suppresses(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    cwd = payload.get('cwd')\n"
            "    if cwd is None:\n"
            "        # hook-cwd-exempt: last-resort fallback when the payload\n"
            "        # lacks a usable cwd.\n"
            "        cwd = os.getcwd()\n"
            "    return cwd\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_empty_annotation_reason_does_not_suppress(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    return payload.get('cwd') or os.getcwd()  # hook-cwd-exempt:\n"
        )
        self.assertTrue(checker.check_python_source(src, FAKE))

    def test_missing_payload_cwd_reference_is_flagged(self) -> None:
        """The historical bug: uses process CWD as the project dir, never reads
        the payload cwd. Even an annotation must not hide this."""
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    # hook-cwd-exempt: intentional\n"
            "    return os.getcwd()\n"
        )
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("never" in f.message and "cwd" in f.message for f in findings))

    def test_compliant_hook_passes(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    cwd = payload.get('cwd')\n"
            "    if cwd is None:\n"
            "        # hook-cwd-exempt: last-resort fallback only.\n"
            "        cwd = os.getcwd()\n"
            "    return cwd\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_no_primitive_no_findings(self) -> None:
        src = "import sys, json\n\n\ndef f():\n    return json.load(sys.stdin).get('tool_input')\n"
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_comment_mentioning_cwd_does_not_satisfy_payload_check(self) -> None:
        """A decoy comment containing 'cwd' must not satisfy check B — the
        payload-cwd reference must be real code, not a string anywhere in
        the file."""
        src = (
            "import os\n\n"
            "# never read cwd from payload, only comment mentions 'cwd'\n"
            "def f():\n"
            "    return os.getcwd()\n"
        )
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("never" in f.message and "cwd" in f.message for f in findings))

    def test_flags_environ_get_pwd(self) -> None:
        src = "import os\n\n\ndef f(payload):\n    return payload.get('cwd') or os.environ.get('PWD')\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any('os.environ.get("PWD")' in f.message for f in findings))

    def test_flags_environ_subscript_pwd(self) -> None:
        src = "import os\n\n\ndef f(payload):\n    return payload.get('cwd') or os.environ['PWD']\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any('os.environ["PWD"]' in f.message for f in findings))

    def test_flags_aliased_path_cwd_import(self) -> None:
        src = "from pathlib import Path as P\n\n\ndef f(payload):\n    return payload.get('cwd') or P.cwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("Path.cwd()" in f.message for f in findings))

    def test_flags_from_os_import_getcwd(self) -> None:
        src = "from os import getcwd\n\n\ndef f(payload):\n    return payload.get('cwd') or getcwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("os.getcwd()" in f.message for f in findings))

    def test_flags_getcwd_after_dotted_submodule_import(self) -> None:
        """`import os.path` (no `as`) binds the top-level name `os`, not
        `os.path` — os.getcwd() must still resolve and be flagged."""
        src = "import os.path\n\n\ndef f(payload):\n    return payload.get('cwd') or os.getcwd()\n"
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("os.getcwd()" in f.message for f in findings))

    def test_literal_dict_cwd_read_does_not_satisfy_payload_check(self) -> None:
        """bento-5ea5: check B was object-blind — it accepted ANY .get("cwd")
        anywhere in the file, even against a hardcoded literal that can't be
        the stdin payload. This must now be flagged."""
        src = (
            "import os\n\n"
            "DEFAULTS = {'cwd': '/tmp/fallback'}\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS.get('cwd')\n"
            "    # hook-cwd-exempt: intentional\n"
            "    return os.getcwd()\n"
        )
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("never" in f.message and "cwd" in f.message for f in findings))

    def test_dict_literal_subscript_cwd_does_not_satisfy_payload_check(self) -> None:
        src = (
            "import os\n\n"
            "DEFAULTS = {'cwd': '/tmp/fallback'}\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS['cwd']\n"
            "    # hook-cwd-exempt: intentional\n"
            "    return os.getcwd()\n"
        )
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(any("never" in f.message and "cwd" in f.message for f in findings))

    def test_dynamic_indirection_through_local_variable_satisfies_check(self) -> None:
        """A name derived from a call (not a literal) still satisfies check B
        even without proving it traces back to the payload — this mirrors
        real hooks like record-bash.py, where the object read is a local
        variable built from a wrapper call, not the payload variable itself."""
        src = (
            "import os\n\n\n"
            "def f(payload):\n"
            "    tool_input = _mapping(payload.get('tool_input'))\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return tool_input.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_module_level_json_load_assignment_satisfies_check(self) -> None:
        src = (
            "import json, os, sys\n\n"
            "hook_input = json.load(sys.stdin)\n\n\n"
            "def f():\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return hook_input.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_subscript_payload_cwd_reference_satisfies_check(self) -> None:
        src = (
            "import os\n\n\ndef f(payload):\n"
            "    if 'cwd' in payload:\n"
            "        return payload['cwd']\n"
            "    # hook-cwd-exempt: fallback when payload lacks cwd\n"
            "    return os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])



class LiteralOnlyBindingFormsTest(unittest.TestCase):
    """bento-5ea5 follow-up: the literal-only decoy filter must not reject a
    genuine payload read just because the payload name happens to also have a
    literal binding. This lint gates every hook in the repo, so a false
    positive here fails CI on a correct hook. Each case below is a binding
    form that leaves the name carrying real stdin input."""

    EXEMPT = "    # hook-cwd-exempt: last-resort fallback only.\n"

    def _assert_clean(self, body: str) -> None:
        src = "import json, os, sys\n\n\n" + body + "\n\ndef _g():\n" + self.EXEMPT + "    return os.getcwd()\n"
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_literal_default_then_update_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    payload = {}\n"
            "    payload.update(json.load(sys.stdin))\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_literal_default_then_setdefault_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    payload = {}\n"
            "    payload.setdefault('cwd', _parse())\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_literal_default_passed_to_call_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    payload = {}\n"
            "    _fill(payload)\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_tuple_unpack_rebind_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    global payload\n"
            "    payload, extra = _parse()\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_for_target_rebind_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    for payload in _iter():\n"
            "        pass\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_with_as_rebind_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    with _open() as payload:\n"
            "        return payload.get('cwd') or _g()\n"
        )

    def test_walrus_rebind_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    if (payload := json.load(sys.stdin)):\n"
            "        return payload.get('cwd') or _g()\n"
        )

    def test_augmented_assign_rebind_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    global payload\n"
            "    payload |= _parse()\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_subscript_read_on_rebound_name_satisfies_check(self) -> None:
        self._assert_clean(
            "payload = {}\n\n\n"
            "def f():\n"
            "    for payload in _iter():\n"
            "        pass\n"
            "    return payload['cwd'] or _g()\n"
        )

    def test_dict_unpack_merge_of_payload_satisfies_check(self) -> None:
        """`{**DEFAULTS, **payload}` is an `ast.Dict` node but carries stdin
        input. Classifying it as a hardcoded literal by node type alone made
        `merged['cwd']` -- the only cwd read in the file -- look like a decoy.
        """
        self._assert_clean(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    payload = json.load(sys.stdin)\n"
            "    merged = {**DEFAULTS, **payload}\n"
            "    return merged['cwd'] or _g()\n"
        )

    def test_list_star_unpack_of_payload_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    items = [*json.load(sys.stdin)]\n"
            "    return items['cwd'] or _g()\n"
        )

    def test_dict_literal_with_non_literal_value_satisfies_check(self) -> None:
        """A dict literal whose *values* come from a call is not hardcoded."""
        self._assert_clean(
            "def f():\n"
            "    d = {'cwd': _parse()}\n"
            "    return d['cwd'] or _g()\n"
        )

    def test_item_assignment_population_satisfies_check(self) -> None:
        """`payload[k] = v` mutates `payload`, but the name sits in Load
        position inside the Store node, so the Name-Store sweep never sees it.
        """
        self._assert_clean(
            "def f():\n"
            "    payload = {}\n"
            "    for k, v in json.load(sys.stdin).items():\n"
            "        payload[k] = v\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_attribute_assignment_population_satisfies_check(self) -> None:
        self._assert_clean(
            "class Box:\n"
            "    pass\n\n\n"
            "def f():\n"
            "    box = Box()\n"
            "    box.data = json.load(sys.stdin)\n"
            "    return box.data.get('cwd') or _g()\n"
        )

    def test_nested_item_assignment_population_satisfies_check(self) -> None:
        """A write through a chain (`state.cache['k'] = v`) mutates the root
        name, so the root must be rescued too."""
        self._assert_clean(
            "def f():\n"
            "    state = {'cache': {}}\n"
            "    state['cache']['cwd'] = json.load(sys.stdin)['cwd']\n"
            "    return state['cache'].get('cwd') or _g()\n"
        )

    def test_chained_write_is_the_only_rescue(self) -> None:
        """Non-vacuous guard for the walk-down to the root name.

        Every other chained-write test is rescued by something else as well --
        a `Subscript`/`Attribute` read base (which `_is_decoy_base` never
        rejects), a dynamically bound receiver, or a second `cwd` read on the
        write line. Here the read base is a bare `Name`, the binding is a
        nested literal, and the sole `cwd` read is `state.get('cwd')`, so the
        chained write `state['cache']['k'] = ...` is the only thing keeping
        `state` out of the literal-only set. Truncating the walk to
        `node.value` flags this source.
        """
        self._assert_clean(
            "def f():\n"
            "    state = {'cache': {}}\n"
            "    state['cache']['k'] = json.load(sys.stdin)\n"
            "    return state.get('cwd') or _g()\n"
        )

    def test_chained_deletion_is_the_only_rescue(self) -> None:
        """Same shape, via `del` rather than assignment."""
        self._assert_clean(
            "def f():\n"
            "    state = {'cache': {'k': 1}}\n"
            "    del state['cache']['k']\n"
            "    return state.get('cwd') or _g()\n"
        )

    def test_parameter_shadowing_a_factory_name_satisfies_check(self) -> None:
        """The literal-factory carve-out applies only to an unshadowed builtin.

        A parameter named `dict` is a binding, so `dict(cfg)` here is an
        arbitrary call that could populate `cfg` in place. Missing `ast.arg`
        made this identical hook clean or flagged depending on the parameter's
        name.
        """
        self._assert_clean(
            "def f(dict):\n"
            "    cfg = {}\n"
            "    dict(cfg)\n"
            "    return cfg.get('cwd') or _g()\n"
        )

    def test_except_as_shadowing_a_factory_name_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    cfg = {}\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as dict:\n"
            "        pass\n"
            "    dict(cfg)\n"
            "    return cfg.get('cwd') or _g()\n"
        )

    def test_except_as_rebinding_satisfies_check(self) -> None:
        """`except ... as name` binds through a plain `str`, not a Name node,
        so the Store sweep never sees it -- but it can bind anything."""
        self._assert_clean(
            "def f():\n"
            "    d = {'cwd': '/tmp'}\n"
            "    try:\n"
            "        pass\n"
            "    except Exception as d:\n"
            "        pass\n"
            "    return d['cwd'] or _g()\n"
        )

    def test_match_as_rebinding_satisfies_check(self) -> None:
        self._assert_clean(
            "def f(obj):\n"
            "    d = {'cwd': '/tmp'}\n"
            "    match obj:\n"
            "        case object() as d:\n"
            "            pass\n"
            "    return d['cwd'] or _g()\n"
        )

    def test_def_rebinding_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    d = {'cwd': '/tmp'}\n"
            "    def d():\n"
            "        pass\n"
            "    return d['cwd'] or _g()\n"
        )

    def test_import_rebinding_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    d = {'cwd': '/tmp'}\n"
            "    import os as d\n"
            "    return d['cwd'] or _g()\n"
        )

    def test_item_deletion_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    payload = {'cwd': '/tmp'}\n"
            "    del payload['cwd']\n"
            "    return payload.get('cwd') or _g()\n"
        )

    def test_payload_copy_accessor_chain_satisfies_check(self) -> None:
        """Closing the `DEFAULTS.copy().get('cwd')` decoy must not reject the
        same shape over a genuine payload."""
        self._assert_clean(
            "def f():\n"
            "    payload = json.load(sys.stdin)\n"
            "    return payload.copy().get('cwd') or _g()\n"
        )

    def test_dict_of_payload_satisfies_check(self) -> None:
        self._assert_clean(
            "def f():\n"
            "    payload = json.load(sys.stdin)\n"
            "    return dict(payload).get('cwd') or _g()\n"
        )


class LiteralOnlyDecoyTest(unittest.TestCase):
    """The other direction: reads that provably cannot be the stdin payload
    must not satisfy check B."""

    EXEMPT = "    # hook-cwd-exempt: intentional\n"

    def _assert_flagged(self, body: str) -> None:
        src = "import os\n\n" + body
        findings = checker.check_python_source(src, FAKE)
        self.assertTrue(
            any("never" in f.message and "cwd" in f.message for f in findings),
            f"expected payload-check violation, got {[f.message for f in findings]}",
        )

    def test_inline_dict_literal_get_is_a_decoy(self) -> None:
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = {'cwd': '/tmp'}.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_inline_dict_literal_subscript_is_a_decoy(self) -> None:
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = {'cwd': '/tmp'}['cwd']\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_os_environ_get_cwd_is_a_decoy(self) -> None:
        """os.environ is the process environment, not the stdin payload."""
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = os.environ.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_os_environ_subscript_cwd_is_a_decoy(self) -> None:
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = os.environ['cwd']\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_single_hop_alias_of_literal_is_a_decoy(self) -> None:
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    d = DEFAULTS\n"
            "    unrelated = d.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_multi_hop_alias_of_literal_is_a_decoy(self) -> None:
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n"
            "MID = DEFAULTS\n\n\n"
            "def f():\n"
            "    d = MID\n"
            "    unrelated = d.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_literal_dict_factory_call_is_a_decoy(self) -> None:
        self._assert_flagged(
            "DEFAULTS = dict(cwd='/tmp')\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_inline_dict_factory_call_is_a_decoy(self) -> None:
        """`dict(cwd='/tmp')` is a decoy once assigned to a name (see
        test_literal_dict_factory_call_is_a_decoy); it must be a decoy inline
        too."""
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = dict(cwd='/tmp').get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_read_only_accessor_chain_over_literal_is_a_decoy(self) -> None:
        """`.copy()` is an allowlisted read-only accessor, so `DEFAULTS` stays
        literal-only -- the chain over it must stay a decoy as well."""
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS.copy().get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_literal_factory_over_literal_name_is_a_decoy(self) -> None:
        """A builtin container factory copies its argument rather than
        populating it, so `dict(DEFAULTS)` is still hardcoded."""
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    unrelated = dict(DEFAULTS).get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_nested_literal_container_is_a_decoy(self) -> None:
        """Inspecting container contents must not accidentally rescue a
        container that is literal all the way down."""
        self._assert_flagged(
            "DEFAULTS = {'nested': {'cwd': '/tmp'}, 'items': (1, 2)}\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS.get('cwd')\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_alias_cycle_satisfies_check(self) -> None:
        """The fixpoint starts empty and only ever adds grounded names, so an
        alias cycle never resolves to literal-only and its read is accepted.
        That direction is deliberate: this lint gates every hook, so erring
        toward acceptance is the cheap error."""
        src = (
            "import os\n\n"
            "a = b\n"
            "b = a\n\n\n"
            "def f():\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return a.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_alias_of_dynamic_name_satisfies_check(self) -> None:
        """An alias chain that bottoms out in a dynamic binding is NOT a
        decoy -- it may carry the real payload."""
        src = (
            "import json, os, sys\n\n"
            "PAYLOAD = json.load(sys.stdin)\n"
            "d = PAYLOAD\n\n\n"
            "def f():\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return d.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_subscript_of_literal_name_is_a_decoy(self) -> None:
        """`_is_decoy_base` must recurse through `Subscript` bases, not just
        read-only method chains, so indexing into a literal-only name stays a
        decoy."""
        self._assert_flagged(
            "DEFAULTS = {'env': {'cwd': '/tmp'}}\n\n\n"
            "def f():\n"
            "    unrelated = DEFAULTS['env']['cwd']\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_subscript_of_literal_list_element_is_a_decoy(self) -> None:
        self._assert_flagged(
            "L = [{'cwd': '/t'}]\n\n\n"
            "def f():\n"
            "    unrelated = L[0]['cwd']\n" + self.EXEMPT + "    return os.getcwd()\n"
        )

    def test_inline_nested_subscript_is_a_decoy(self) -> None:
        self._assert_flagged(
            "\ndef f():\n"
            "    unrelated = {'e': {'cwd': '/t'}}['e']['cwd']\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_subscript_of_dynamic_name_satisfies_check(self) -> None:
        """The Subscript recursion must not turn a genuine payload read into
        a false positive."""
        src = (
            "import json, os, sys\n\n"
            "payload = json.load(sys.stdin)\n\n\n"
            "def f():\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return payload['nested']['cwd'] or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_dict_factory_over_literal_temp_var_is_a_decoy(self) -> None:
        """`D2 = dict(DEFAULTS)` must not bypass the `_is_decoy_base`
        recursion just because it is assigned to a temp variable first."""
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    D2 = dict(DEFAULTS)\n"
            "    unrelated = D2.get('cwd')\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_copy_accessor_over_literal_temp_var_is_a_decoy(self) -> None:
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    D2 = DEFAULTS.copy()\n"
            "    unrelated = D2.get('cwd')\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_dict_factory_over_dynamic_temp_var_satisfies_check(self) -> None:
        """The alias tracing for `dict(NAME)` / `NAME.copy()` must not rescue
        a temp variable derived from a genuine payload."""
        src = (
            "import json, os, sys\n\n"
            "payload = json.load(sys.stdin)\n\n\n"
            "def f():\n"
            "    D2 = dict(payload)\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return D2.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_get_accessor_with_arg_over_literal_temp_var_is_a_decoy(self) -> None:
        """`_decoy_dependencies`'s read-only-accessor branch must not require
        zero arguments -- `D2 = DEFAULTS.get('env')` is exactly as literal as
        `DEFAULTS`, the same as the inline `DEFAULTS.get('env')['cwd']` chain
        `_is_decoy_base` already accepts with no arity restriction."""
        self._assert_flagged(
            "DEFAULTS = {'env': {'cwd': '/tmp'}}\n\n\n"
            "def f():\n"
            "    D2 = DEFAULTS.get('env')\n"
            "    unrelated = D2['cwd']\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_subscript_rhs_over_literal_temp_var_is_a_decoy(self) -> None:
        """`_decoy_dependencies` must recurse through a Subscript-shaped RHS,
        not just Call-shaped ones -- `X = DEFAULTS['env']` is exactly as
        literal as `DEFAULTS`, mirroring the Subscript-base recursion
        `_is_decoy_base` already does for inline chains."""
        self._assert_flagged(
            "DEFAULTS = {'env': {'cwd': '/tmp'}}\n\n\n"
            "def f():\n"
            "    X = DEFAULTS['env']\n"
            "    unrelated = X['cwd']\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_multi_arg_factory_over_literal_temp_var_is_a_decoy(self) -> None:
        """`_decoy_dependencies`'s factory branch must accept any number of
        decoy-shaped positional/keyword arguments, not just a single bare
        name -- `D2 = dict(DEFAULTS, extra=1)` is exactly as literal as the
        inline `dict(DEFAULTS, extra=1).get('cwd')` chain `_is_decoy_base`
        already accepts."""
        self._assert_flagged(
            "DEFAULTS = {'cwd': '/tmp'}\n\n\n"
            "def f():\n"
            "    D2 = dict(DEFAULTS, extra=1)\n"
            "    unrelated = D2.get('cwd')\n"
            + self.EXEMPT
            + "    return os.getcwd()\n"
        )

    def test_multi_arg_factory_with_dynamic_arg_over_temp_var_satisfies_check(
        self,
    ) -> None:
        """A multi-arg factory call is only a decoy if *every* argument is --
        one dynamic argument must rescue the whole temp-variable binding."""
        src = (
            "import json, os, sys\n\n"
            "DEFAULTS = {'cwd': '/tmp'}\n"
            "payload = json.load(sys.stdin)\n\n\n"
            "def f():\n"
            "    D2 = dict(DEFAULTS, extra=payload)\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return D2.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])

    def test_shadowed_dict_factory_is_not_treated_as_literal(self) -> None:
        """If `dict` is rebound in the file, `dict(...)` is an ordinary call,
        so the name stays dynamic and its read is accepted."""
        src = (
            "import os\n\n\n"
            "def dict(**kwargs):\n"
            "    return _parse()\n\n\n"
            "def f():\n"
            "    payload = dict(cwd='/tmp')\n"
            "    # hook-cwd-exempt: last-resort fallback only.\n"
            "    return payload.get('cwd') or os.getcwd()\n"
        )
        self.assertEqual(checker.check_python_source(src, FAKE), [])


class ShellCheckTest(unittest.TestCase):
    def test_flags_unannotated_pwd(self) -> None:
        src = 'cwd="$(echo "$payload" | jq -r .cwd)"\ndir="${cwd:-$PWD}"\n'
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("$PWD" in f.message for f in findings))

    def test_annotation_above_suppresses_pwd(self) -> None:
        src = (
            "cwd=$(python3 -c \"import json,sys; print(json.load(sys.stdin).get('cwd') or '')\")\n"
            "# hook-cwd-exempt: last-resort default.\n"
            'dir="${cwd:-$PWD}"\n'
        )
        self.assertEqual(checker.check_shell_source(src, FAKE_SH), [])

    def test_flags_embedded_python_getcwd(self) -> None:
        src = "out=$(python3 -c \"import os; print(cwd or os.getcwd())\")\n# uses d.get('cwd')\n"
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("os.getcwd()" in f.message for f in findings))

    def test_missing_cwd_reference_flagged_in_shell(self) -> None:
        src = 'dir="$PWD"  # hook-cwd-exempt: deliberate\n'
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("never" in f.message for f in findings))

    def test_comment_only_pwd_not_flagged(self) -> None:
        src = "cwd=$(jq -r .cwd)\n# do not use $PWD here\ndir=$cwd\n"
        self.assertEqual(checker.check_shell_source(src, FAKE_SH), [])

    def test_comment_mentioning_cwd_does_not_satisfy_payload_check(self) -> None:
        """A decoy comment containing 'cwd' must not satisfy the payload-cwd
        check for a real $PWD usage with no genuine payload read."""
        src = 'dir="$PWD"  # totally reads "cwd" from somewhere, trust me\n'
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("never" in f.message for f in findings))

    def test_literal_only_cwd_string_does_not_satisfy_payload_check(self) -> None:
        """A hardcoded literal that merely contains the string 'cwd' -- never
        read from anything -- must not satisfy the payload-cwd check for a
        real $PWD fallback with no genuine payload read. Shell mirror of the
        Python-side literal-only-decoy fix (bento-5ea5)."""
        src = (
            "DEFAULT_KEY='cwd'\n"
            'dir="$PWD"  # hook-cwd-exempt: deliberate\n'
        )
        findings = checker.check_shell_source(src, FAKE_SH)
        self.assertTrue(any("never" in f.message for f in findings))


if __name__ == "__main__":
    unittest.main()
