# AI Video Generator — ITS Marketing
> Generate cinematic promotional videos using the LTX API (ltx-2-3-fast / ltx-2-3-pro).

---

## Prerequisites

- Python 3.10 or higher (`py --version` to check)
- An LTX API key — get one at [ltx.video](https://ltx.video)

---

## Step 1 — Install Dependencies

Open a terminal, navigate to this folder, then install the required packages:

```cmd
cd "Capstone-01-Backend\ai-service"
py -m pip install -r requirements.txt
```

---

## Step 2 — Set Your API Key

Create a file named `.env` inside this `ai-service` folder (if it doesn't exist yet):

```
ai-service/
└── .env       ← create this file
```

Add the following content to `.env`:

```env
LTX_API_KEY=your_actual_ltx_api_key_here
```

Replace `your_actual_ltx_api_key_here` with your real key from the LTX dashboard.

> **Note:** The `.env` file is gitignored — your key will never be committed to the repository.

### Optional `.env` settings

```env
LTX_API_KEY=your_actual_ltx_api_key_here

# Output folder for generated videos (default: outputs/videos)
VIDEO_OUTPUT_DIR=outputs/videos

# Log folder (default: outputs/logs)
LOG_DIR=outputs/logs

# Log verbosity: DEBUG | INFO | WARNING | ERROR (default: INFO)
LOG_LEVEL=INFO
```

---

## Step 3 — Run the Generator

Make sure you are inside the `ai-service` folder before running any command:

```cmd
cd "Capstone-01-Backend\ai-service"
```

### Send a prompt directly from the terminal

```cmd
py run_trial.py --prompt "Your video description here..." --duration 12 --task-type text_to_video
```

**Example (ITS Informatics promo):**

```cmd
py run_trial.py --prompt "A cinematic 10-second promotional video for Informatics Engineering at ITS Surabaya. The video features a 20-year-old Indonesian male student with a smart and friendly appearance, wearing a navy blue varsity jacket, smiling confidently at the camera. The scene starts in a modern, sunlit campus courtyard with tropical greenery, then transitions to a high-tech computer lab with glowing screens displaying complex AI code and 3D data visualizations. The final shot is a majestic drone view of the iconic ITS campus architecture during golden hour. The video includes high-quality native audio with a professional, enthusiastic male voiceover in Indonesian saying: Wujudkan masa depan digitalmu di Teknik Informatika ITS. Cerdas, Kreatif, Berprestasi!. Ambient tech sounds and upbeat corporate music play in the background. No subtitles or text on screen. Hyper-realistic, 4k, professional cinematography, cinematic lighting." --duration 12 --task-type text_to_video
```

---

## CLI Flags Reference

| Flag | Short | Default | Options | Description |
|---|---|---|---|---|
| `--prompt` | `-p` | *(loads prompts.json)* | Any text | Video description to generate |
| `--duration` | `-d` | `12` | `1` – `12` | Video length in seconds |
| `--ratio` | `-r` | `16:9` | `16:9` `9:16` `1:1` `4:3` | Aspect ratio |
| `--task-type` | `-t` | `text_to_video` | see below | Model selection (Fast vs Pro) |
| `--id` | | auto | Any string | Custom video ID |
| `--limit` | `-n` | `1` | Any number | Max scenes per run (`0` = all) |
| `--prompts-file` | | `prompts.json` | File path | Batch prompt file |

---

## Choosing a Model

| `--task-type` | Model | Speed | Quality | Best for |
|---|---|---|---|---|
| `text_to_video` | `ltx-2-3-fast` | Fast | Good | Testing / drafts |
| `text_to_video_hq` | `ltx-2-3-pro` | Slower | High | Final renders |

**Fast (for testing):**
```cmd
py run_trial.py --prompt "..." --task-type text_to_video
```

**Pro (for final output):**
```cmd
py run_trial.py --prompt "..." --task-type text_to_video_hq
```

---

## Batch Mode (Multiple Prompts)

You can define multiple prompts in `prompts.json` and run them in batch.

**Format of `prompts.json`:**
```json
[
  {
    "id": "scene_01",
    "prompt": "First scene description...",
    "duration": 12,
    "ratio": "16:9",
    "task_type": "text_to_video_hq"
  },
  {
    "id": "scene_02",
    "prompt": "Second scene description...",
    "duration": 10,
    "ratio": "16:9",
    "task_type": "text_to_video"
  }
]
```

**Run only the first scene (default):**
```cmd
py run_trial.py
```

**Run all scenes in the file:**
```cmd
py run_trial.py --limit 0
```

**Run the first 3 scenes:**
```cmd
py run_trial.py --limit 3
```

---

## Output

### Generated video
```
ai-service/outputs/videos/{video-id}__{model}.mp4
```

Example:
```
outputs/videos/cli_20260506_162300__ltx_ltx-2-3-pro.mp4
```

### Terminal result summary

On **success**, the terminal will display:
```
  ✅  VIDEO GENERATED SUCCESSFULLY
  Video ID    : cli_20260506_162300
  Status      : SUCCESS
  Model       : ltx-2-3-pro
  Duration    : 12s
  Audio       : YES ✓
  File Size   : 2048.5 KB
  Saved to    : outputs/videos/cli_20260506_162300__ltx_ltx-2-3-pro.mp4
```

On **failure**, the terminal will display:
```
  ❌  VIDEO GENERATION FAILED
  Video ID    : cli_20260506_162300
  Status      : FAILED
  Model       : ltx:ltx-2-3-pro
  Reason      : API returned error 401 [HTTP 401]
```

### JSON report
A detailed report is also saved after every run:
```
ai-service/outputs/reports/trial_report_{timestamp}.json
```

---

## Audio Notes

- **ltx-2-3-fast** and **ltx-2-3-pro** both support native audio generation.
- Audio is enabled by default (`generate_audio: true`).
- The `audio_length` parameter is always set equal to `duration` to prevent audio cutoff.
- Maximum duration is **12 seconds** to ensure full audio coverage.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `'python' is not recognized` | Python not on PATH | Use `py` instead of `python` |
| `ModuleNotFoundError: No module named 'dotenv'` | Dependencies not installed | Run `py -m pip install -r requirements.txt` |
| `LTX_API_KEY tidak ditemukan` | Missing `.env` file or empty key | Create `.env` with your API key |
| `API returned error 401` | Invalid API key | Check your key at [ltx.video](https://ltx.video) |
| `No such file or directory: run_trial.py` | Wrong working directory | `cd` into the `ai-service` folder first |
| Audio cuts off before video ends | Missing `audio_length` in payload | Already fixed — update to latest code |

---

## Project Structure

```
ai-service/
├── .env                    ← Your API keys (create this, never commit)
├── run_trial.py            ← Main CLI runner
├── main.py                 ← FastAPI web server (optional)
├── prompts.json            ← Default batch prompts
├── requirements.txt        ← Python dependencies
├── providers/
│   ├── ltx_provider.py     ← LTX API integration
│   ├── router.py           ← Task-type to model routing
│   └── http_client.py      ← HTTP session with retry logic
├── services/
│   └── ai_video_service.py ← Job management service
└── outputs/
    ├── videos/             ← Generated .mp4 files
    ├── reports/            ← JSON run reports
    └── logs/               ← Log files
```
