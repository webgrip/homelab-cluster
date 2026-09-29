import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNTIME_PATCHES = Path(os.environ.get("LITELLM_RUNTIME_PATCHES", REPO / "kubernetes/apps/ai/litellm/app/litellm-runtime-patches.configmap.yaml"))
HELMRELEASE = REPO / "kubernetes/apps/ai/litellm/app/helmrelease.yaml"
PINNED_IMAGE = os.environ.get("LITELLM_PINNED_IMAGE", "")
SITE_PACKAGES_IN_IMAGE = "/app/.venv/lib/python3.13/site-packages"
SENTINEL = "spend-log-sentinel-4f1c9e"
REDACTED = {"redacted": True}

PROBE = textwrap.dedent(f"""
    import datetime
    import json

    from litellm.litellm_core_utils import litellm_logging
    from litellm.proxy.spend_tracking import spend_tracking_utils

    sentinel = {SENTINEL!r}
    now = datetime.datetime.now(datetime.timezone.utc)


    def tool_call():
        return {{"name": "query", "arguments": {{"query": sentinel}}, "result": {{"text": sentinel}},
                "namespaced_tool_name": "omnigraph_brain/query", "mcp_server_name": "omnigraph_brain"}}


    def logged(call):
        logging_obj = litellm_logging.Logging(model="MCP: query", messages=[], stream=False, call_type="call_mcp_tool",
                                              start_time=now, litellm_call_id="call-1", function_id="function-1")
        logging_obj.update_environment_variables(model="MCP: query", user=None, optional_params={{}},
                                                 litellm_params={{"metadata": {{"user_api_key_alias": "probe"}}, "litellm_call_id": "call-1"}})
        if call is not None:
            logging_obj.model_call_details["mcp_tool_call_metadata"] = call
        standard = litellm_logging.get_standard_logging_object_payload(
            kwargs=logging_obj.model_call_details, init_response_obj={{"content": [{{"type": "text", "text": "ok"}}]}},
            start_time=now, end_time=now, logging_obj=logging_obj, status="success")
        spend_kwargs = dict(logging_obj.model_call_details)
        spend_kwargs["standard_logging_object"] = standard
        spend_kwargs["completion_start_time"] = now
        payload = spend_tracking_utils.get_logging_payload(spend_kwargs, {{"content": []}}, now, now)
        return standard, payload


    call = tool_call()
    standard, payload = logged(call)
    plain_standard, plain_payload = logged(None)
    direct = spend_tracking_utils._get_spend_logs_metadata(metadata={{"user_api_key_alias": "probe"}}, mcp_tool_call_metadata=tool_call())
    print(json.dumps({{
        "standard_mcp": standard["metadata"].get("mcp_tool_call_metadata"),
        "standard_leaks": sentinel in json.dumps(standard, default=str),
        "spend_log_mcp": json.loads(payload["metadata"]).get("mcp_tool_call_metadata"),
        "spend_log_leaks": sentinel in json.dumps(payload, default=str),
        "spend_log_tool": payload.get("mcp_namespaced_tool_name"),
        "direct_spend_log_mcp": direct.get("mcp_tool_call_metadata"),
        "direct_spend_log_leaks": sentinel in json.dumps(direct, default=str),
        "tool_call_after_logging": call,
        "plain_standard_mcp": plain_standard["metadata"].get("mcp_tool_call_metadata"),
        "plain_spend_log_mcp": json.loads(plain_payload["metadata"]).get("mcp_tool_call_metadata"),
    }}))
""")

FAKE_LITELLM = {
    "httpx/__init__.py": """
        class Timeout:
            def __init__(self, seconds):
                self.seconds = seconds


        class AsyncClient:
            def __init__(self, *args, **kwargs):
                self.kwargs = kwargs
    """,
    "litellm/__init__.py": "",
    "litellm/litellm_core_utils/__init__.py": "",
    "litellm/litellm_core_utils/litellm_logging.py": """
        class Logging:
            def __init__(self, **kwargs):
                self.model_call_details = {}

            def update_environment_variables(self, **kwargs):
                self.model_call_details["litellm_params"] = kwargs["litellm_params"]


        class StandardLoggingPayloadSetup:
            @staticmethod
            def get_standard_logging_metadata(metadata, litellm_params=None, mcp_tool_call_metadata=None):
                return {"user_api_key_alias": (metadata or {}).get("user_api_key_alias"), "mcp_tool_call_metadata": mcp_tool_call_metadata}


        def get_standard_logging_object_payload(kwargs, init_response_obj, start_time, end_time, logging_obj, status):
            metadata = StandardLoggingPayloadSetup.get_standard_logging_metadata(
                metadata=kwargs["litellm_params"]["metadata"], mcp_tool_call_metadata=kwargs.get("mcp_tool_call_metadata"))
            return {"metadata": metadata, "call_type": "call_mcp_tool", "status": status}
    """,
    "litellm/proxy/__init__.py": "",
    "litellm/proxy/spend_tracking/__init__.py": "",
    "litellm/proxy/spend_tracking/spend_tracking_utils.py": """
        import json


        def _get_spend_logs_metadata(metadata, mcp_tool_call_metadata=None):
            return {"user_api_key_alias": (metadata or {}).get("user_api_key_alias"), "mcp_tool_call_metadata": mcp_tool_call_metadata}


        def get_logging_payload(kwargs, response_obj, start_time, end_time):
            standard = kwargs["standard_logging_object"]
            clean = _get_spend_logs_metadata(kwargs["litellm_params"]["metadata"], mcp_tool_call_metadata=standard["metadata"].get("mcp_tool_call_metadata"))
            call = clean.get("mcp_tool_call_metadata")
            return {"metadata": json.dumps(clean), "call_type": standard["call_type"],
                    "mcp_namespaced_tool_name": call.get("namespaced_tool_name") if call else None}
    """,
}


def sitecustomize_source(configmap=RUNTIME_PATCHES):
    lines = Path(configmap).read_text(encoding="utf-8").split("\n")
    start = lines.index("  sitecustomize.py: |-")
    body = []
    for line in lines[start + 1:]:
        if line.startswith("    ") or not line.strip():
            body.append(line[4:])
            continue
        break
    return "\n".join(body).rstrip() + "\n"


def pinned_image_from_helmrelease():
    lines = HELMRELEASE.read_text(encoding="utf-8").split("\n")
    for index, line in enumerate(lines):
        if line.strip() == "repository: ghcr.io/berriai/litellm-database":
            tag = lines[index + 1].split("tag:", 1)[1].strip()
            return f"ghcr.io/berriai/litellm-database:{tag}"
    raise AssertionError("the LiteLLM image is not pinned in helmrelease.yaml")


def run_probe_on_fakes(sitecustomize):
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        for relative, source in FAKE_LITELLM.items():
            path = root / "modules" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
        site = root / "site"
        site.mkdir()
        (site / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")
        (root / "probe.py").write_text(PROBE, encoding="utf-8")
        environment = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        environment["PYTHONPATH"] = f"{site}{os.pathsep}{root / 'modules'}"
        completed = subprocess.run([sys.executable, str(root / "probe.py")], env=environment, capture_output=True, text=True, timeout=60)
        return completed


def run_probe_in_image(image, sitecustomize):
    with tempfile.TemporaryDirectory() as work:
        root = Path(work)
        (root / "sitecustomize.py").write_text(sitecustomize, encoding="utf-8")
        (root / "probe.py").write_text(PROBE, encoding="utf-8")
        root.chmod(0o755)
        for name in ("sitecustomize.py", "probe.py"):
            (root / name).chmod(0o644)
        return subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--entrypoint", "/app/.venv/bin/python",
             "-v", f"{root / 'sitecustomize.py'}:{SITE_PACKAGES_IN_IMAGE}/sitecustomize.py:ro",
             "-v", f"{root / 'probe.py'}:/probe.py:ro", image, "/probe.py"],
            capture_output=True, text=True, timeout=600)


def probe_result(completed):
    if completed.returncode != 0:
        raise AssertionError(f"the probe failed with exit {completed.returncode}: {completed.stderr[-2000:]}")
    return json.loads(completed.stdout.strip().split("\n")[-1])


class RedactionContract:
    result = None

    def test_the_standard_logging_payload_carries_no_mcp_arguments(self):
        self.assertFalse(self.result["standard_leaks"])
        self.assertEqual(self.result["standard_mcp"]["arguments"], REDACTED)

    def test_the_spend_log_row_carries_no_mcp_arguments(self):
        self.assertFalse(self.result["spend_log_leaks"])
        self.assertEqual(self.result["spend_log_mcp"]["arguments"], REDACTED)

    def test_the_spend_log_builder_redacts_even_an_unredacted_tool_call(self):
        self.assertFalse(self.result["direct_spend_log_leaks"])
        self.assertEqual(self.result["direct_spend_log_mcp"]["arguments"], REDACTED)

    def test_a_tool_result_is_redacted_too(self):
        self.assertEqual(self.result["standard_mcp"]["result"], REDACTED)
        self.assertEqual(self.result["direct_spend_log_mcp"]["result"], REDACTED)

    def test_the_tool_name_and_server_stay_for_spend_attribution(self):
        self.assertEqual(self.result["spend_log_tool"], "omnigraph_brain/query")
        self.assertEqual(self.result["spend_log_mcp"]["name"], "query")
        self.assertEqual(self.result["spend_log_mcp"]["mcp_server_name"], "omnigraph_brain")

    def test_the_live_tool_call_keeps_its_arguments(self):
        self.assertEqual(self.result["tool_call_after_logging"]["arguments"], {"query": SENTINEL})

    def test_a_call_without_mcp_metadata_is_left_alone(self):
        self.assertIsNone(self.result["plain_standard_mcp"])
        self.assertIsNone(self.result["plain_spend_log_mcp"])


class FakeLiteLLMModules(RedactionContract, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = probe_result(run_probe_on_fakes(sitecustomize_source()))

    def test_the_probe_detects_a_leak_when_no_patch_is_loaded(self):
        result = probe_result(run_probe_on_fakes(""))
        self.assertTrue(result["standard_leaks"])
        self.assertTrue(result["spend_log_leaks"])
        self.assertTrue(result["direct_spend_log_leaks"])


@unittest.skipUnless(PINNED_IMAGE and shutil.which("docker"), "set LITELLM_PINNED_IMAGE to run the probe on the pinned LiteLLM image")
class PinnedLiteLLMImage(RedactionContract, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = probe_result(run_probe_in_image(PINNED_IMAGE, sitecustomize_source()))

    def test_the_probe_detects_a_leak_when_no_patch_is_loaded(self):
        result = probe_result(run_probe_in_image(PINNED_IMAGE, ""))
        self.assertTrue(result["standard_leaks"])
        self.assertTrue(result["spend_log_leaks"])
        self.assertTrue(result["direct_spend_log_leaks"])

    def test_the_image_under_test_is_the_one_deployed(self):
        self.assertEqual(PINNED_IMAGE.split("@", 1)[-1], pinned_image_from_helmrelease().split("@", 1)[-1])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--print-pinned-image":
        print(pinned_image_from_helmrelease())
        sys.exit(0)
    unittest.main()
