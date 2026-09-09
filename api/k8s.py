import asyncio
import json
import os
import threading
import time
from collections.abc import AsyncGenerator
from pathlib import Path

IMAGE = os.environ.get("KRATOS_IMAGE", "quay.io/wparker/kratos:latest")
NAMESPACE = os.environ.get("NAMESPACE", "kratos")
_GLOBAL_CM = "kratos-global-config"

_DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
_LOGS_DIR = _DATA_DIR / "logs"

# SSE keepalive comment emitted when no log lines are available.
# Proxy buffers (HAProxy, nginx, Vite dev proxy) flush on each SSE "event",
# including comments, which prevents buffering the stream until close.
_KEEPALIVE_INTERVAL_S = 1.0


def _kube():
    from kubernetes import client as k8s, config as k8s_cfg

    try:
        k8s_cfg.load_incluster_config()
    except k8s_cfg.ConfigException:
        k8s_cfg.load_kube_config()
    return k8s


def _api_server_node(k8s: object) -> str | None:
    """Return the node name the API server pod is running on, or None if unknown."""
    try:
        core = k8s.CoreV1Api()  # type: ignore[attr-defined]
        pods = core.list_namespaced_pod(
            namespace=NAMESPACE, label_selector="app=kratos"
        )
        if pods.items:
            return pods.items[0].spec.node_name
    except Exception:
        pass
    return None


def create_job(scenario: str, run_id: str, config_overrides: dict | None = None) -> None:
    k8s = _kube()
    batch = k8s.BatchV1Api()

    node_name = _api_server_node(k8s)

    extra_env = [
        k8s.V1EnvVar(
            name="KRATOS_CONFIG_OVERRIDES",
            value=json.dumps(config_overrides or {}),
        )
    ]

    pod_spec = k8s.V1PodSpec(
        service_account_name="kratos",
        restart_policy="Never",
        node_name=node_name,
        containers=[
            k8s.V1Container(
                name="harness",
                image=IMAGE,
                command=["python", "-m", "harness.main"],
                args=[
                    "--scenario",
                    f"{os.environ.get('SCENARIOS_DIR', '/app/scenarios')}/{scenario}.yaml",
                    "--run-id",
                    run_id,
                ],
                env=extra_env,
                env_from=[
                    k8s.V1EnvFromSource(
                        config_map_ref=k8s.V1ConfigMapEnvSource(name=_GLOBAL_CM)
                    )
                ],
                volume_mounts=[
                    k8s.V1VolumeMount(name="data", mount_path="/data"),
                ],
            )
        ],
        volumes=[
            k8s.V1Volume(
                name="data",
                persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                    claim_name="kratos-data"
                ),
            )
        ],
    )

    safe_scenario = scenario.lower().replace("_", "-")[:12].rstrip("-")
    job_name = f"kratos-{safe_scenario}-{run_id[:6]}"

    job = k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=job_name),
        spec=k8s.V1JobSpec(
            ttl_seconds_after_finished=3600,
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels={"kratos-run-id": run_id}),
                spec=pod_spec,
            ),
        ),
    )
    batch.create_namespaced_job(namespace=NAMESPACE, body=job)


def _serve_log_file(log_file: Path) -> list[str]:
    """Read a complete log file and return SSE-formatted chunks."""
    return [
        f"data: {line}\n\n"
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line
    ]


async def stream_pod_logs(run_id: str) -> AsyncGenerator[str, None]:
    log_file = _LOGS_DIR / f"{run_id}.log"
    tmp_file = _LOGS_DIR / f"{run_id}.log.tmp"

    # Fast path: complete log already on disk (pod may be long gone).
    if log_file.exists() and log_file.stat().st_size > 0:
        for chunk in _serve_log_file(log_file):
            yield chunk
        return

    _LOGS_DIR.mkdir(parents=True, exist_ok=True)

    done = threading.Event()

    def _stream_and_write() -> None:
        """Run entirely in one thread: find pod → stream logs → write to tmp file.

        Keeping all kubernetes client calls in a single thread avoids urllib3
        cross-thread issues and lets the event loop stay unblocked.
        """
        try:
            k8s = _kube()
            core = k8s.CoreV1Api()
            label = f"kratos-run-id={run_id}"

            pod_name: str | None = None
            for _ in range(30):  # wait up to 60 s
                pods = core.list_namespaced_pod(
                    namespace=NAMESPACE, label_selector=label
                )
                if pods.items:
                    pod_name = pods.items[0].metadata.name
                    break
                time.sleep(2)

            if pod_name is None:
                print(f"[k8s] pod not found for run {run_id}", flush=True)
                return

            log_stream = core.read_namespaced_pod_log(
                name=pod_name,
                namespace=NAMESPACE,
                follow=True,
                _preload_content=False,
            )
            with tmp_file.open("w", encoding="utf-8") as f:
                for raw in log_stream.stream():
                    line = raw.decode(errors="replace").rstrip()
                    if line:
                        f.write(line + "\n")
                        f.flush()
        except Exception as exc:
            print(f"[k8s] log stream error for {run_id}: {exc}", flush=True)
        finally:
            done.set()

    thread = threading.Thread(target=_stream_and_write, daemon=True)
    thread.start()

    # Poll the tmp file for new content every 100 ms, yielding each new line
    # as an SSE event.  The event loop never blocks — all k8s I/O is in the
    # background thread above.
    #
    # A keepalive SSE comment (": keepalive") is emitted every second when
    # there are no new lines.  Intermediate proxies (HAProxy, Vite dev proxy,
    # nginx) flush their buffers on each SSE "event", including comments, so
    # this prevents the entire stream from being held until the connection closes.
    position = 0
    last_activity = time.monotonic()

    while True:
        sent_any = False

        if tmp_file.exists():
            try:
                with tmp_file.open("r", encoding="utf-8") as f:
                    f.seek(position)
                    data = f.read()
                    position = f.tell()
                for line in data.splitlines():
                    if line:
                        yield f"data: {line}\n\n"
                        sent_any = True
            except OSError:
                pass

        if sent_any:
            last_activity = time.monotonic()
        elif time.monotonic() - last_activity >= _KEEPALIVE_INTERVAL_S:
            yield ": keepalive\n\n"
            last_activity = time.monotonic()

        if done.is_set():
            # Final drain — pick up any lines written between last poll and done.
            if tmp_file.exists():
                try:
                    with tmp_file.open("r", encoding="utf-8") as f:
                        f.seek(position)
                        data = f.read()
                    for line in data.splitlines():
                        if line:
                            yield f"data: {line}\n\n"
                except OSError:
                    pass
            break

        await asyncio.sleep(0.1)

    thread.join(timeout=10)
    # Atomically promote temp file; future requests are served from disk.
    if tmp_file.exists():
        try:
            tmp_file.rename(log_file)
        except OSError:
            pass
