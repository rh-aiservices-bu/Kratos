from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.k8s import stream_pod_logs

router = APIRouter()


@router.get("/api/runs/{run_id}/logs")
async def get_run_logs(run_id: str) -> StreamingResponse:
    async def _generate() -> AsyncGenerator[str, None]:
        async for chunk in stream_pod_logs(run_id):
            yield chunk

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
