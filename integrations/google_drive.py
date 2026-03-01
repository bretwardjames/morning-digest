"""Google Drive integration for uploading/downloading PDFs and managing folder structure."""

import logging
from pathlib import Path

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

FOLDER_STRUCTURE = {
    "inbox": "inbox",
    "liked": "liked",
    "disliked": "disliked",
    "feedback": "feedback",
    "archive": "archive",
}


class GoogleDriveClient:
    def __init__(self, credentials_file: str, token_file: str = "credentials/drive_token.json"):
        self.credentials_file = credentials_file
        self.token_file = token_file
        self.service = None

    def authenticate(self) -> None:
        """Authenticate with Google Drive API. Opens browser on first run."""
        creds = None
        token_path = Path(self.token_file)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, SCOPES)
                creds = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())

        self.service = build("drive", "v3", credentials=creds)
        logger.info("Google Drive authenticated successfully")

    def ensure_folder_structure(self, config: dict) -> dict:
        """Create Boox Digest folder structure if it doesn't exist.
        Returns dict of folder_name -> folder_id.
        """
        root_folder_id = self._find_or_create_folder("Boox Digest")
        folder_ids = {}

        for key, name in FOLDER_STRUCTURE.items():
            config_key = f"{key}_folder_id"
            existing_id = config.get("drive", {}).get(config_key, "")

            if existing_id:
                folder_ids[key] = existing_id
            else:
                folder_ids[key] = self._find_or_create_folder(name, parent_id=root_folder_id)

        return folder_ids

    def upload_pdf(self, local_path: str, folder_id: str) -> str:
        """Upload a PDF file to a specific Drive folder. Returns file ID."""
        file_metadata = {
            "name": Path(local_path).name,
            "parents": [folder_id],
        }
        media = MediaFileUpload(local_path, mimetype="application/pdf")
        file = self.service.files().create(
            body=file_metadata, media_body=media, fields="id"
        ).execute()

        file_id = file.get("id")
        logger.info(f"Uploaded {Path(local_path).name} -> {file_id}")
        return file_id

    def list_files(self, folder_id: str, modified_since: str | None = None) -> list[dict]:
        """List PDF files in a folder, optionally filtered by modification date."""
        query = f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false"
        if modified_since:
            query += f" and modifiedTime > '{modified_since}'"

        results = self.service.files().list(
            q=query, fields="files(id, name, modifiedTime)", orderBy="modifiedTime desc"
        ).execute()

        return results.get("files", [])

    def download_file(self, file_id: str, local_path: str) -> None:
        """Download a file from Drive to a local path."""
        request = self.service.files().get_media(fileId=file_id)
        content = request.execute()

        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        Path(local_path).write_bytes(content)
        logger.info(f"Downloaded {file_id} -> {local_path}")

    def move_file(self, file_id: str, destination_folder_id: str) -> None:
        """Move a file to a different folder."""
        file = self.service.files().get(fileId=file_id, fields="parents").execute()
        previous_parents = ",".join(file.get("parents", []))

        self.service.files().update(
            fileId=file_id,
            addParents=destination_folder_id,
            removeParents=previous_parents,
            fields="id, parents",
        ).execute()
        logger.info(f"Moved {file_id} to folder {destination_folder_id}")

    def _find_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Find a folder by name or create it. Returns folder ID."""
        query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.service.files().list(q=query, fields="files(id)").execute()
        files = results.get("files", [])

        if files:
            return files[0]["id"]

        metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = self.service.files().create(body=metadata, fields="id").execute()
        logger.info(f"Created folder '{name}' -> {folder['id']}")
        return folder["id"]
