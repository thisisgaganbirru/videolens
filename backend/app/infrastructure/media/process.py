"""The one way this app runs ffmpeg/ffprobe: with a hard deadline, killed on
timeout and on cancellation.

arq cancels a job's coroutine at its timeout, and the API's request task is
cancelled when a client goes away; without the kill the child process keeps
running (the event loop's child watcher still holds it), so a worker with a
small `max_jobs` could carry extra encoders against a directory that is
about to be deleted. `communicate()` reads stdout and stderr together, so a
chatty process can never block on a full pipe.
"""

import asyncio


async def run_process(command: list[str], *, timeout: float, stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    """(return code, stdout, stderr). Raises `TimeoutError` once `timeout`
    seconds pass, having killed and reaped the process; a cancellation is
    re-raised the same way."""
    proc = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except BaseException:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        raise
    return proc.returncode if proc.returncode is not None else -1, stdout, stderr
