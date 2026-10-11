# ASOFAB Transcriber

Turns a Google Meet or Drive recording of an ASOFAB session into a speaker-attributed Turkish/English transcript, with a review queue for everything the machine is unsure about. Processing is local: the recording is cached on your computer, never copied to another cloud, and no audio goes to third-party AI services.

## Use it (Windows)
1. Unzip `ASOFAB-Transcriber-windows.zip` and run `ASOFAB-Transcriber.exe`. A console window shows status and your browser opens the app. No Python, FFmpeg or CUDA install is needed.
2. Do the one-time setup in [SETUP_GOOGLE.md](SETUP_GOOGLE.md) (Google OAuth client and a Hugging Face token).
3. Paste a `meet.google.com/xxx-xxxx-xxx` link, a Drive recording link, or a `conferenceRecords/...` id, then **Analyze Recording**.
4. On **Speakers**, play the sample clips for each voice and assign Haso, Uğur, Ulaç or Taylan (skippable if Meet metadata already identified them). Optionally build voice prototypes to check every segment.
5. Fix flagged items in **To Be Checked**, edit text in **Transcript**, then **Export**.

A Meet *room* link names no particular recording. The app lists every historical instance it finds and picks the best match (you can override). A Drive file link names one recording and the app says so.

## Outputs
`ASOFAB_Full_Transcript.md` (no timestamps), `ASOFAB_To_Be_Checked.csv`, `ASOFAB_Transcript.json`, `ASOFAB.srt`, `ASOFAB_Chapter_Source.md` (source material only, no chapter is written).

## How accuracy and identity are handled
- **ASR**: Whisper large-v3 (faster-whisper), Turkish primary with a per-segment English second pass for code-switching. Chunks are 10 min with 24 s overlap; each word is kept from exactly one chunk. Phantom phrases on silence are dropped and counted. It never swaps to a smaller model by itself; a smaller one needs `allow_smaller_model` in settings.json.
- **Hardware**: NVIDIA GPU is used automatically (float16, or int8 under 6 GB VRAM, same model). Without one it runs on CPU, which is accurate but slow (roughly 1.5 to 4 times the recording length). Every stage saves progress, so Stop/Resume and per-stage Retry work.
- **Diarization**: pyannote 3.1 over the whole file in one pass, so voice IDs never reset between chunks. Four speakers is a prior: tiny, very similar clusters are merged, distinct ones are kept and flagged.
- **Identity evidence, strongest first**: your confirmation, Meet transcript entries joined to participant records, voice prototypes from your confirmed samples, then bare clustering (which names nobody). Names spoken in conversation are never used. Stereo channels are never treated as people. Unresolved voices are labelled `Unknown Speaker [to be checked]`. The Recording tab lists which evidence sources were truly available.
- **Glossary**: editable in the app. Aliases (how it sounds) are separate from preferred spellings. Aliases that are ordinary words are flagged, not replaced. Joke names are never "corrected".

## Run from source (developers)
```
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121   # or the CPU build
pip install -r requirements.txt
python run_app.py
python -m pytest        # needs requirements-dev.txt and ffmpeg
```
`ASOFAB_ALLOW_LOCAL=1` lets you paste a local media path as the "link" for offline testing. Data lives in `%LOCALAPPDATA%\ASOFAB`.

## Building the Windows app
Windows executables cannot be built from Linux. Push this repo to GitHub and run the **Build Windows app** workflow (`.github/workflows/build-windows.yml`); it runs the tests, bundles Python, FFmpeg and the NVIDIA runtime DLLs with PyInstaller, smoke-starts the exe and uploads the zip.

## What was and was not tested
Tested (56 automated tests, Linux): link parsing; conference-record selection; glossary behaviour; chunk planning, boundary dedup and cache-based resume; hallucination filter; word-to-speaker assignment including interruptions, overlap and identity across a chunk boundary; cluster consolidation; attribution hierarchy, unknown-speaker handling and honest evidence reporting; ffprobe/ffmpeg on a real mixed-stereo MP4; review items, correction persistence (including across a re-draft) and omission fill-in; the web UI page and every export endpoint over HTTP; all five exports; stage resume/retry ordering; the HTTP API token and host guard.

**Not tested, because no credentials, models or Windows machine were available:** live Google Meet/Drive calls (written against the v2/v3 docs, never run against Google); Whisper and pyannote output quality on real Turkish speech (the tests use simulated model outputs); voice-prototype embedding; GPU paths; the browser UI in a real browser (it was served and its token substitution checked, but its buttons were never clicked); the PyInstaller build and a clean-Windows run (the CI workflow exists but has not been run). Expect to find and fix some packaging issues on the first CI build.

## Known limitations
- No visual (active-speaker highlight) cross-check yet.
- Heavily overlapping speech yields one text stream; it is flagged, not reconstructed.
- IC/OOC labelling is a cautious keyword heuristic; most lines stay `Uncertain IC/OOC` until you classify them.
- Whisper large-v3 is strong but not perfect on informal Turkish; use To Be Checked.
