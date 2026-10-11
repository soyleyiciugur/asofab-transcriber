name: Build Windows app
on:
  workflow_dispatch:
  push:
    tags: ["v*"]

jobs:
  build:
    runs-on: windows-latest
    timeout-minutes: 90
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install FFmpeg
        shell: pwsh
        run: |
          choco install ffmpeg-full -y --no-progress
          New-Item -ItemType Directory -Force build/bin | Out-Null
          Copy-Item (Get-Command ffmpeg).Source build/bin/ffmpeg.exe
          Copy-Item (Get-Command ffprobe).Source build/bin/ffprobe.exe

      - name: Install dependencies (CUDA build of PyTorch)
        shell: pwsh
        run: |
          python -m pip install --upgrade pip
          pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
          pip install -r requirements-dev.txt

      - name: Run tests
        run: python -m pytest -q

      - name: Build executable
        run: pyinstaller asofab.spec --noconfirm

      - name: Smoke test the executable
        shell: pwsh
        run: |
          $env:ASOFAB_PORT = "8765"
          $env:ASOFAB_NO_BROWSER = "1"
          $env:ASOFAB_HOME = "$PWD/smoke-data"
          $p = Start-Process -FilePath "dist/ASOFAB-Transcriber/ASOFAB-Transcriber.exe" -PassThru -RedirectStandardError smoke.err
          $ok = $false
          for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 2
            try {
              $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765/
              if ($r.Content -match "ASOFAB TRANSCRIBER") { $ok = $true; break }
            } catch {}
          }
          Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
          if (-not $ok) { Get-Content smoke.err -ErrorAction SilentlyContinue; throw "exe did not serve the UI" }

      - name: Package
        shell: pwsh
        run: |
          Copy-Item README.md, SETUP_GOOGLE.md dist/ASOFAB-Transcriber/
          Compress-Archive -Path dist/ASOFAB-Transcriber/* -DestinationPath ASOFAB-Transcriber-windows.zip

      - uses: actions/upload-artifact@v4
        with:
          name: ASOFAB-Transcriber-windows
          path: ASOFAB-Transcriber-windows.zip
