# Morning Digest

Autonomous morning digest agent that curates articles and surfaces important emails as PDFs delivered to a Boox tablet via Google Drive sync.

## How it works

1. **Article curation** — Claude searches the web for articles matching your topic preferences, selects a set that fits a ~35 minute reading window, and renders each as a PDF with a fillable feedback form
2. **Email triage** — Reads 3 email accounts (2 Gmail + 1 Outlook), scores each email's importance using Claude, and renders high-priority emails as PDFs with a blank notes page
3. **Drive delivery** — Uploads all PDFs to a Google Drive folder that syncs to the Boox Go 10.3
4. **Feedback loop** — On each run, checks for returned feedback forms (filled in on the Boox), parses ratings and freeform text, and stores preference signals in ragtime memory. Quality improves over time.

## Setup

### Prerequisites

- Python 3.11+
- [ragtime](https://github.com/your-org/ragtime) CLI installed
- Google Cloud project with Gmail API + Drive API enabled
- Azure AD app registration (if using Outlook)
- Anthropic API key

### Install

```bash
git clone https://github.com/YOUR_USERNAME/morning-digest.git
cd morning-digest
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
```

### Google OAuth (Gmail + Drive)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable **Gmail API** and **Google Drive API**
3. Create OAuth2 credentials (Desktop app type)
4. Download the credentials JSON for each Gmail account to `credentials/gmail_primary.json` and `credentials/gmail_secondary.json`
5. On first run, a browser window will open for consent
6. Scopes requested: `gmail.readonly`, `gmail.compose`, `drive.file`

### Microsoft Outlook

1. Go to [Azure Portal](https://portal.azure.com/) → App registrations → New registration
2. Redirect URI: `http://localhost:8080`
3. Add delegated API permissions: `Mail.Read`, `Mail.ReadWrite`
4. Note the client ID and tenant ID → add to `.env`
5. On first run, a device code flow will prompt for auth

> **Note:** Microsoft does not offer a draft-only OAuth scope. `Mail.ReadWrite` is the minimum required to create drafts. This also technically permits modifying/deleting mail. The application code never does this, but the permission cannot be restricted further at the API level.

### Boox Setup

1. Install Google Drive app on Boox Go 10.3
2. Sign in with the same Google account as Gmail primary
3. Enable sync for the `/Boox Digest/inbox/` folder
4. Set NeoReader as default PDF handler

### Configure

Edit `config.yaml` to set your topic preferences, email accounts, and reading window target.

### Schedule

```bash
chmod +x cron/setup.sh
./cron/setup.sh
```

This installs a cron job that runs daily at 5am Mountain Time.

## Drive Folder Structure

```
/Boox Digest/
  /inbox/          ← Agent drops all PDFs here each morning
  /liked/          ← Move articles here for "more like this" signal
  /disliked/       ← Move articles here for "less like this" signal
  /feedback/       ← Annotated PDFs return here after Boox sync
  /archive/        ← Agent moves processed files here
```

The folder structure is auto-created on first run.

## Testing

```bash
pytest tests/
```

## Manual Run

```bash
python main.py
```

## Architecture

| Component | Purpose |
|---|---|
| `agents/curator.py` | Article discovery via Claude + web_search |
| `agents/email_processor.py` | Email importance scoring |
| `agents/feedback_parser.py` | PDF form parsing + ragtime storage |
| `generators/article_pdf.py` | Article → PDF with feedback form |
| `generators/email_pdf.py` | Email → PDF with notes page |
| `integrations/gmail.py` | Gmail API wrapper |
| `integrations/outlook.py` | Microsoft Graph API wrapper |
| `integrations/google_drive.py` | Drive upload/download/folder management |
| `integrations/ragtime.py` | ragtime memory client |
| `main.py` | Orchestrator |
