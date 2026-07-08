# Release v2.0 — Three-Pipeline Architecture + Multilingual Web UI

> Release date: 2026-06-15

## Overview

v2.0 is a complete architectural refactor from a single-file script to an engineered application with three distinct video generation pipelines, a four-layer backend, WebSocket real-time progress, and a 7-language internationalized frontend.

---

## Features

### Three Task Types
- **Simple Video** — Single prompt → single video, exposing all 9 Agnes API parameters (t2v/i2v/ti2vid/keyframes)
- **Creative Video** — AI screenwriter → storyboards → per-scene videos → edge_tts narration → fine-grained subtitles → concatenation
- **Manuscript Video** — Long text splitting → AI scene prompt → per-paragraph videos → unified TTS+subtitles → concatenation

### Architecture
- `core/api/` — Agnes Chat / Image / Video API wrappers with retry and polling
- `core/audio/` — edge_tts engine (word-level timestamps) + SRT subtitle generation + moviepy overlay
- `core/compositor/` — Video concatenation, scaling, frame extraction, silent audio generation
- `core/pipelines/` — Three pipeline implementations (simple / creative / manuscript)
- `models/` — Pydantic v2 data models with persistent task state serialization

### Web UI
- Three-tab frontend (Simple / Creative / Manuscript), Tailwind CDN single-page
- 7 languages: 中文 / English / Русский / 日本語 / 한국어 / Bahasa Melayu / Bahasa Indonesia
- WebSocket real-time progress push
- Task pause, resume, and stop

### Subtitle System
- edge_tts word-level timestamps → fine-grained SRT grouping
- CJK multi-line wrapping (break at punctuation)
- `method="caption"` rendering, supports stroke / background / position customization

### Other
- One-click startup script `start.sh`
- `docs/system_design.md` system design document
- 3 demo videos embedded in README

---

## Stats

```
40 files changed, 11,268 insertions(+), 2,792 deletions(-)
```

### New Files
| File | Description |
|------|-------------|
| `core/pipelines/` | Three pipeline types (simple / creative / manuscript) |
| `core/api/` | Agnes API wrapper layer |
| `core/audio/` | TTS + subtitle engine |
| `core/compositor/` | Video compositing / processing |
| `models/task.py` | Three task subtype data models |
| `scripts/regression_runner.py` | Regression test script |
| `docs/system_design.md` | System design document |
| `docs/regression_test_plan.md` | Test plan |

---

## Upgrade Notes

- Python 3.10+ required
- New dependencies: `edge_tts>=6.1.0`, `srt>=3.5.0`
- Run `./start.sh` for one-click startup, or `.venv/bin/pip install -r requirements.txt && .venv/bin/python server.py`
