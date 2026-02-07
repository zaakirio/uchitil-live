<p align="center">
  <img src="docs/banner.png" alt="Uchitil Live Banner" width="100%" />
</p>

<h1 align="center">Uchitil Live</h1>

<p align="center">
  <strong>Privacy-first AI tutoring session recorder</strong><br>
  Record, transcribe, and summarize your language tutoring sessions — entirely on your own hardware.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Tauri-2.x-FFC7C7?style=flat-square&logo=tauri&logoColor=black" alt="Tauri 2" />
  <img src="https://img.shields.io/badge/Rust-1.75+-FFC7C7?style=flat-square&logo=rust&logoColor=black" alt="Rust" />
  <img src="https://img.shields.io/badge/Next.js-14-FFC7C7?style=flat-square&logo=next.js&logoColor=black" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.100+-FFC7C7?style=flat-square&logo=fastapi&logoColor=black" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Whisper-Local_STT-FFC7C7?style=flat-square&logo=openai&logoColor=black" alt="Whisper" />
  <img src="https://img.shields.io/badge/License-MIT-FFC7C7?style=flat-square" alt="MIT License" />
</p>

---

## What is Uchitil Live?

Uchitil Live captures your tutoring sessions on platforms like **Preply**, **iTalki**, and **ClassIn**, then generates structured notes with vocabulary, grammar points, corrections, and homework — all processed locally with no data leaving your machine.

Built for language learners who want organised session notes without trusting a third-party service with their audio.

## Features

- **Dual audio capture** — Records both your microphone and system audio simultaneously
- **Local transcription** — Whisper.cpp / Parakeet running on-device with GPU acceleration (Metal, CUDA, Vulkan)
- **AI-powered session notes** — Extracts vocabulary, grammar points, pronunciation notes, corrections, and homework
- **Voice Activity Detection** — Only processes speech segments, reducing transcription load by ~70%
- **Professional audio mixing** — RMS-based ducking, clipping prevention, real-time level monitoring
- **Multiple LLM providers** — Ollama (local), Claude, Groq, OpenRouter, or any OpenAI-compatible endpoint
- **Session history** — Browse, search, and revisit past session transcripts and summaries
- **Cross-platform** — macOS (Metal), Windows (CUDA/Vulkan), Linux (CUDA/Vulkan)

## Design

<p align="center">
  <img src="uchitil-live.png" alt="Uchitil Live Icon" width="128" />
</p>

| Token | Hex | Usage |
|-------|-----|-------|
| ![#F6F6F6](https://via.placeholder.com/12/F6F6F6/F6F6F6.png) Off-white | `#F6F6F6` | Background |
| ![#FFE2E2](https://via.placeholder.com/12/FFE2E2/FFE2E2.png) Light pink | `#FFE2E2` | Secondary / accent background |
| ![#FFC7C7](https://via.placeholder.com/12/FFC7C7/FFC7C7.png) Medium pink | `#FFC7C7` | Primary accent, buttons, badges |
| ![#AAAAAA](https://via.placeholder.com/12/AAAAAA/AAAAAA.png) Muted gray | `#AAAAAA` | Secondary text, borders |

## Tech Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                    Desktop App (Tauri 2 + Rust)                 │
│  ┌──────────────────┐  ┌─────────────────┐  ┌────────────────┐ │
│  │   Next.js 14     │  │  Rust Backend   │  │ Whisper Engine │ │
│  │  (React 18 / TS) │←→│  (Audio + IPC)  │←→│  (Local STT)   │ │
│  └──────────────────┘  └─────────────────┘  └────────────────┘ │
└────────────────────────────────┬────────────────────────────────┘
                                 │ HTTP
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI + Python)                    │
│  ┌────────────┐  ┌────────────────────┐  ┌────────────────────┐ │
│  │  MongoDB   │←→│  Session Manager   │←→│  LLM Provider     │ │
│  │  Atlas     │  │  (CRUD + Summary)  │  │  (Ollama / etc.)  │ │
│  └────────────┘  └────────────────────┘  └────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- **Rust** 1.75+ and **Cargo**
- **Node.js** 18+ and **pnpm**
- **Python** 3.10+ and **pip**
- **Ollama** (for local LLM summaries) — [ollama.ai](https://ollama.ai)
- **macOS 13+** for system audio capture via ScreenCaptureKit

### One-command launch

```bash
# Starts the backend server + builds and opens the .app bundle
./start.sh
```

This will:
1. Start the FastAPI backend on `http://localhost:5167`
2. Build the Tauri `.app` bundle (with proper macOS permission entitlements)
3. Sign and launch `Uchitil Live.app`

### Other modes

```bash
./start.sh dev       # Fast dev mode (pnpm tauri dev — no .app bundle, no permission dialogs)
./start.sh backend   # Backend only
./start.sh stop      # Stop all services
```

### Manual setup

<details>
<summary><strong>Frontend (Tauri desktop app)</strong></summary>

```bash
cd frontend
pnpm install
pnpm run tauri:dev          # Development
pnpm run tauri:build        # Production build
```

GPU-specific builds:
```bash
pnpm run tauri:dev:metal    # macOS Metal
pnpm run tauri:dev:cuda     # NVIDIA CUDA
pnpm run tauri:dev:vulkan   # AMD/Intel Vulkan
pnpm run tauri:dev:cpu      # CPU-only
```

</details>

<details>
<summary><strong>Backend (FastAPI server)</strong></summary>

```bash
cd backend
pip install -r requirements.txt
./clean_start_backend.sh    # Starts on http://localhost:5167
```

API docs at [http://localhost:5167/docs](http://localhost:5167/docs).

</details>

<details>
<summary><strong>Docker</strong></summary>

```bash
./run-docker.sh start --interactive   # macOS / Linux
.\run-docker.ps1 start -Interactive   # Windows
```

</details>

## Project Layout

```
├── frontend/                 # Tauri desktop app
│   ├── src/                  # Next.js pages + React components
│   ├── src-tauri/
│   │   ├── src/
│   │   │   ├── audio/        # Audio capture, mixing, VAD, recording
│   │   │   ├── whisper_engine/ # Local Whisper.cpp integration
│   │   │   └── api/          # Rust → Backend API bridge
│   │   ├── icons/            # App icons (all sizes)
│   │   └── templates/        # Tutoring summary templates
│   └── public/               # Static assets
├── backend/                  # FastAPI server
│   └── app/
│       ├── main.py           # API endpoints
│       ├── db.py             # MongoDB (motor) database layer
│       └── transcript_processor.py  # LLM summarisation
├── docs/                     # Documentation + banner
└── start.sh                  # One-command launcher
```

## How Session Notes Work

When you finish a recording, Uchitil Live sends the transcript to an LLM and extracts structured tutoring notes:

| Section | What it captures |
|---------|-----------------|
| **Vocabulary Learned** | New words and phrases introduced during the session |
| **Grammar Points** | Grammar rules discussed or corrected |
| **Pronunciation Notes** | Pronunciation guidance and corrections |
| **Corrections Made** | Specific mistakes and their corrections |
| **Key Phrases** | Useful expressions and idioms practised |
| **Conversation Topics** | What you talked about |
| **Homework** | Assignments or practice tasks from the tutor |
| **Progress Notes** | Observations on improvement and areas to work on |

## Contributing

Contributions are welcome. Open an issue for bugs or ideas, or submit a pull request.

## License

MIT
