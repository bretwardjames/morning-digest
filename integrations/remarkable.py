"""reMarkable tablet integration via ddvk/rmapi CLI.

Requires rmapi to be installed:
    go install github.com/ddvk/rmapi@latest
    # or: brew install io41/tap/rmapi

First-time setup:
    rmapi  (follow the device registration prompt)
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


class RemarkableClient:
    def __init__(self, rmapi_path: str = "rmapi"):
        self.rmapi_path = rmapi_path
        self._verify_installed()

    def _verify_installed(self) -> None:
        """Check that rmapi is available."""
        try:
            result = subprocess.run(
                [self.rmapi_path, "version"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                logger.info(f"rmapi available: {result.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError(
                "rmapi not found. Install it: go install github.com/ddvk/rmapi@latest"
            )

    def ensure_folder(self, folder_path: str) -> None:
        """Create a folder on the Remarkable if it doesn't exist.

        Args:
            folder_path: Path like '/Morning Digest' or '/Morning Digest/Archive'
        """
        # rmapi mkdir is idempotent — it won't error if the folder exists
        parts = folder_path.strip("/").split("/")
        current = ""
        for part in parts:
            current += f"/{part}"
            self._run(["mkdir", current])

    def upload_pdf(self, local_path: str, destination_folder: str = "/") -> bool:
        """Upload a PDF to a folder on the Remarkable.

        Args:
            local_path: Path to the local PDF file.
            destination_folder: Remarkable folder path (e.g. '/Morning Digest').

        Returns:
            True if upload succeeded.
        """
        result = self._run(["put", local_path, destination_folder])
        if result and result.returncode == 0:
            logger.info(f"Uploaded to Remarkable: {local_path} -> {destination_folder}")
            return True
        logger.error(f"Failed to upload {local_path}")
        return False

    def list_files(self, folder_path: str = "/") -> list[str]:
        """List files in a Remarkable folder."""
        result = self._run(["ls", folder_path], capture=True)
        if result and result.stdout:
            return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]
        return []

    def move_file(self, source: str, destination: str) -> bool:
        """Move a file on the Remarkable."""
        result = self._run(["mv", source, destination])
        return result is not None and result.returncode == 0

    def delete_file(self, path: str) -> bool:
        """Delete a file from the Remarkable."""
        result = self._run(["rm", path])
        return result is not None and result.returncode == 0

    def _run(self, args: list[str], capture: bool = False) -> subprocess.CompletedProcess | None:
        """Run an rmapi command."""
        cmd = [self.rmapi_path] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True if capture else False,
                text=True,
                timeout=120,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.PIPE,
            )
            if result.returncode != 0 and result.stderr:
                # rmapi mkdir returns non-zero if folder exists — that's fine
                if "mkdir" in args and "already exists" in (result.stderr or ""):
                    return result
                logger.warning(f"rmapi {' '.join(args)}: {result.stderr.strip()}")
            return result
        except subprocess.TimeoutExpired:
            logger.error(f"rmapi timed out: {' '.join(args)}")
            return None
