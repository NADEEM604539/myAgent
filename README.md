# MyAgent

MyAgent is a Windows desktop AI assistant with a chat and voice interface. It uses a LangGraph ReAct agent to answer prompts and call tools, including browser-based tasks on the NUST learning management system (LMS). The UI displays model responses and agent/tool activity.

## Features

- Chat with an OpenAI-compatible language model; the agent streams responses and tool activity into the UI.
- Record voice messages from a microphone and transcribe them locally with Faster Whisper.
- Ask the agent for system information, the current time, or a calculation.
- Sign in to NUST LMS in a visible browser, find courses, and open quizzes or assignments.
- Download course materials and previously submitted assignment files.
- Inspect assignment submission details, upload a file, or remove an existing submission.

LMS operations use a visible Chrome or Playwright Chromium window and an authenticated browser session. Removing a submission cannot be undone. Replacing an existing submission removes the old submission first; only ask the agent to do either when you intend that change. An uploaded assignment file may be saved as a draft; if the assignment still shows a **Submit assignment** button, submit it in the LMS to finalize it.

## Project layout

```text
backend/
  agent.py          LangGraph agent setup and streamed conversation handling
  tools.py          General tools and the combined agent tool list
  lms_tools.py      NUST LMS browser, course, resource, and submission tools
  transcription.py  Local WAV validation and Faster Whisper transcription
frontend/
  main.py           Flet desktop chat, activity panel, and voice recording UI
requirements.txt    Python runtime dependencies
setup.bat           Windows environment and browser setup
agent.bat           Windows app launcher
.env.example        Safe configuration template (copied to .env on setup)
```

## Requirements

- Windows 10 or later.
- Python 3.10 or later.
- An OpenAI API key and a model name supported by the configured API endpoint.
- A microphone for voice input (optional).
- NUST LMS credentials for LMS features (optional).
- Internet access to install packages, call the model API, access the LMS, and download the Whisper model the first time voice transcription is used.

## Setup

1. Open a Command Prompt in the project folder.
2. Run:

   ```bat
   setup.bat
   ```

   This creates `venv` if needed, installs `requirements.txt`, installs Playwright Chromium, and creates `.env` from `.env.example` if `.env` does not already exist. It does not overwrite an existing `.env`.

3. Edit `.env` and set at least `OPENAI_API_KEY` and `MODEL`:

   ```dotenv
   OPENAI_API_KEY=your_api_key
   MODEL=gpt-4o-mini
   BASEURL=

   NADEEM_LMS_USERNAME=
   NADEEM_LMS_PASSWORD=
   ```

   `BASEURL` is optional for the default OpenAI API; set it when using a compatible provider or custom endpoint. Set LMS credentials only if you want LMS features. For another account prefix, add matching variables such as `STUDENT_LMS_USERNAME` and `STUDENT_LMS_PASSWORD`, then ask the agent to use that account name.

4. Start MyAgent:

   ```bat
   agent.bat
   ```

   Alternatively, run `venv\Scripts\python.exe frontend\main.py` from the project folder.

## Using the app

- Type a request and select **Send** to chat with the agent.
- Select the microphone button to begin recording; select it again to stop and send. Audio is transcribed locally and sent to the configured language model as text. The first voice request downloads the selected Whisper model.
- Ask the agent to log in to the LMS before requesting a course or assignment task. For example: “Log in to NUST LMS as NADEEM, then open my course named …”
- LMS files are saved under `Desktop\MyAgent LMS` by default. Set `LMS_DOWNLOAD_DIR` in `.env` to use another directory.
- After uploading an assignment, check its status in the LMS and finalize it there if it remains a draft.

The agent's conversation history is held in memory while the app is running; it is not saved as a chat history file.

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes | API credential used by the language model client. |
| `MODEL` | Yes | Model identifier accepted by the selected API endpoint. |
| `BASEURL` | No | Base URL for an OpenAI-compatible API; leave empty for the default endpoint. |
| `<NAME>_LMS_USERNAME` | For LMS login | Username for the account prefix supplied to the LMS login tool. |
| `<NAME>_LMS_PASSWORD` | For LMS login | Password for the corresponding account prefix. |
| `LMS_DOWNLOAD_DIR` | No | Overrides the default Desktop download location. |
| `LOCAL_WHISPER_MODEL` | No | Faster Whisper model name; defaults to `base`. |

Keep `.env` private. It is ignored by Git; do not commit API keys or LMS passwords. `.env.example` contains placeholders only.

## Troubleshooting

- **Missing or invalid API key:** Check `OPENAI_API_KEY` in `.env`, then close and restart the app after editing it.
- **Model/API error:** Verify `MODEL` and, if applicable, `BASEURL` against your provider's settings.
- **Browser will not start:** Run `setup.bat` again to install Playwright Chromium. The app tries installed Chrome first and falls back to Playwright Chromium.
- **LMS login fails:** Check the account-specific username/password variables and ensure the NUST LMS is reachable. You can also complete sign-in manually in the opened browser tab if the LMS requires an additional step.
- **Microphone unavailable:** Check Windows microphone permissions and the selected recording device. Voice capture expects mono, 16 kHz, 16-bit PCM audio.
- **First transcription is slow:** Faster Whisper downloads and caches the model on first use; subsequent requests reuse it.

## Dependencies

Runtime dependencies are listed in [requirements.txt](requirements.txt). There is no separate test suite currently included in the repository.
