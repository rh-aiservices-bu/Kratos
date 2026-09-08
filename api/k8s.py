import asyncio
import os
from collections.abc import AsyncGenerator

IMAGE = os.environ.get("KRATOS_IMAGE", "quay.io/wparker/kratos:latest")
NAMESPACE = os.environ.get("NAMESPACE", "kratos")
_GLOBAL_CM = "kratos-global-config"


def _kube():
    from kubernetes import client as k8s, config as k8s_cfg

    try:
        k8s_cfg.load_incluster_config()
    except k8s_cfg.ConfigException:
        k8s_cfg.load_kube_config()
    return k8s


def create_job(scenario: str, run_id: str) -> None:
    k8s = _kube()
    batch = k8s.BatchV1Api()
    job = k8s.V1Job(
        metadata=k8s.V1ObjectMeta(name=f"kratos-{run_id[:8]}"),
        spec=k8s.V1JobSpec(
            ttl_seconds_after_finished=3600,
            template=k8s.V1PodTemplateSpec(
                metadata=k8s.V1ObjectMeta(labels={"kratos-run-id": run_id}),
                spec=k8s.V1PodSpec(
                    service_account_name="kratos",
                    restart_policy="Never",
                    containers=[
                        k8s.V1Container(
                            name="harness",
                            image=IMAGE,
                            command=["python", "-m", "harness.main"],
                            args=["--scenario", scenario, "--run-id", run_id],
                            env_from=[
                                k8s.V1EnvFromSource(
                                    config_map_ref=k8s.V1ConfigMapEnvSource(name=_GLOBAL_CM)
                                )
                            ],
                        )
                    ],
                ),
            ),
        ),
    )
    batch.create_namespaced_job(namespace=NAMESPACE, body=job)


async def stream_pod_logs(run_id: str) -> AsyncGenerator[str, None]:
    k8s = _kube()
    core = k8s.CoreV1Api()
    label = f"kratos-run-id={run_id}"

    pod_name: str | None = None
    for _ in range(30):
        pods = core.list_namespaced_pod(namespace=NAMESPACE, label_selector=label)
        if pods.items:
            pod_name = pods.items[0].metadata.name
            break
        await asyncio.sleep(2)

    if pod_name is None:
        yield f'data: {{"event":"error","data":"pod not found for run {run_id}"}}\n\n'
        return

    log_stream = core.read_namespaced_pod_log(
        name=pod_name,
        namespace=NAMESPACE,
        follow=True,
        _preload_content=False,
    )
    for raw in log_stream.stream():
        line = raw.decode().rstrip()
        if line:
            yield f"data: {line}\n\n"
