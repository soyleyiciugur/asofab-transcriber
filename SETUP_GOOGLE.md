# Google setup (one time, about 10 minutes)

Google does not let an app read Meet or Drive data without an OAuth client. There is no way around this, so you create a small private one in your own Google Cloud project. Nothing is billed.

## 1. Create a project and enable two APIs
1. Go to https://console.cloud.google.com/ and create a project (any name, e.g. `asofab-transcriber`).
2. **APIs & Services > Library**: enable **Google Meet REST API** and **Google Drive API**.

## 2. Configure the consent screen
1. **APIs & Services > OAuth consent screen**. Choose **External**, fill the app name and your email.
2. Add your own Google account under **Test users**.
3. Scopes the app requests (both read-only):
   - `https://www.googleapis.com/auth/meetings.space.readonly`
   - `https://www.googleapis.com/auth/drive.readonly`

> While the app is in **Testing** mode, Google expires the sign-in after **7 days**. The app will tell you to reconnect. Publishing the consent screen as "In production" removes that, but Google then shows an "unverified app" warning that you can click through for your own account.

## 3. Create the OAuth client
1. **Credentials > Create credentials > OAuth client ID**, application type **Desktop app**.
2. Download the JSON. Open it in a text editor and paste the whole text into the app under **Settings > Google setup > Save OAuth client**.
3. Click **Connect Google Account** and approve the two read-only permissions.

## What you must have access to
- **Meet metadata** (participants, transcripts): you need to be the meeting organizer or a participant. Meet keeps conference records and transcript entries only for a limited time, so for older sessions you will get recording audio only. The app detects this and continues.
- **Recording file**: you need view access to the recording in Drive. Recordings are saved in the organizer's Drive.

## Hugging Face token (for speaker separation)
The diarization model is gated. Once:
1. Create a free account at https://huggingface.co.
2. Accept the terms at https://hf.co/pyannote/speaker-diarization-3.1 and https://hf.co/pyannote/segmentation-3.0 (and https://hf.co/pyannote/wespeaker-voxceleb-resnet34-LM for voice calibration).
3. Create a **read** token (Settings > Access Tokens) and paste it under **Settings > Models and processing**.

Everything else (Whisper large-v3, about 3 GB) downloads automatically on first use. After that, audio never leaves your computer.
