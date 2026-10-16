import asyncio
import os
import sys
import wave
from pathlib import Path
import flet as ft
import sounddevice as sd
from dotenv import load_dotenv

# Make the project root importable when launched as `python frontend/main.py`.
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import backend LangGraph streaming engine and tool list
from backend.agent import run_agent_stream
from backend.transcription import transcribe_audio
from backend.tools import ALL_TOOLS

load_dotenv()

# Version-agnostic attribute lookup for Flet 1.0+
Colors = getattr(ft, "Colors", getattr(ft, "colors", None))
Icons = getattr(ft, "Icons", getattr(ft, "icons", None))
Padding = getattr(ft, "Padding", getattr(ft, "padding", None))
BorderRadius = getattr(ft, "BorderRadius", getattr(ft, "border_radius", None))
Border = getattr(ft, "Border", getattr(ft, "border", None))

def color(*names: str):
    for name in names:
        if hasattr(Colors, name):
            return getattr(Colors, name)
    raise AttributeError(f"None of the supported color names exist: {', '.join(names)}")

WHITE_10 = color("WHITE_10", "WHITE10")
WHITE_54 = color("WHITE_54", "WHITE54")
WHITE_70 = color("WHITE_70", "WHITE70")
BACKGROUND = color("BACKGROUND", "SURFACE_CONTAINER_LOWEST")
SURFACE_VARIANT = color("SURFACE_VARIANT", "SURFACE_CONTAINER_HIGH")

async def main(page: ft.Page):
    # --- Page Setup ---
    page.title = "LangGraph Local Agent Controller"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0B1017"
    page.padding = 0
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 720
    page.window.min_height = 600

    # --- UI State Containers ---
    sidebar_width = 236
    log_panel_width = 300
    page_width = page.width or page.window.width or 1200
    show_sidebar = page_width > 1120
    show_activity = page_width > 820
    chat_row_width = max(
        240,
        page_width
        - 32
        - 28
        - (sidebar_width if show_sidebar else 0)
        - (log_panel_width if show_activity else 0)
        - 32,
    )
    bubble_width = max(220, min(620, chat_row_width * 0.88))
    chat_bubbles = []
    log_cards = []
    chat_list = ft.ListView(expand=True, spacing=16, padding=18, auto_scroll=True)
    mcp_logs = ft.ListView(expand=True, spacing=8, padding=12, auto_scroll=True)
    recording_stream = None
    recording_frames = []
    recording_errors = []
    recording_path = Path.home() / "AppData" / "Local" / "MyAgent" / "voice_message.wav"
    
    # --- UI Component Builders ---
    def create_chat_bubble(message: str, sender: str):
        is_user = sender == "user"
        bg_color = "#1D4ED8" if is_user else "#1B2532"
        align = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        sender_color = "#BFDBFE" if is_user else "#A5B4FC"
        
        bubble = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(
                        Icons.PERSON_ROUNDED if is_user else Icons.AUTO_AWESOME,
                        size=14,
                        color=sender_color,
                    ),
                    ft.Text(
                        "You" if is_user else "Agent",
                        size=11,
                        weight=ft.FontWeight.BOLD,
                        color=sender_color,
                    ),
                ], spacing=6, tight=True),
                ft.Text(
                    message,
                    size=14,
                    selectable=True,
                    color="#F8FAFC",
                ),
            ], spacing=8, tight=True),
            width=bubble_width,
            padding=Padding.all(14),
            bgcolor=bg_color,
            border_radius=BorderRadius.all(16),
        )
        chat_row = ft.Row(
            width=chat_row_width,
            alignment=align,
            controls=[bubble],
        )
        chat_bubbles.append((chat_row, bubble))
        return chat_row

    async def log_mcp_event(event_text: str, level: str = "INFO"):
        color_map = {
            "INFO": Colors.BLUE_400,
            "TOOL": Colors.AMBER_400,
            "SUCCESS": Colors.GREEN_400,
            "ERROR": Colors.RED_400,
        }
        log_text = event_text if len(event_text) <= 400 else f"{event_text[:397]}..."
        log_card = ft.Container(
                width=log_panel_width - 56,
                padding=Padding.all(10),
                bgcolor="#151D28",
                border_radius=BorderRadius.all(10),
                content=ft.Column([
                    ft.Text(
                        level,
                        size=10,
                        weight=ft.FontWeight.BOLD,
                        color=color_map.get(level, WHITE_70),
                    ),
                    ft.Text(
                        log_text,
                        size=11,
                        color="#CBD5E1",
                        selectable=True,
                    ),
                ], spacing=4, tight=True),
            )
        mcp_logs.controls.append(log_card)
        log_cards.append(log_card)
        page.update()

    async def add_agent_message(text: str):
        chat_list.controls.append(create_chat_bubble(text, "agent"))
        page.update()

    # --- Header / Backend Connection Status ---
    status_indicator = ft.Container(
        width=8,
        height=8,
        border_radius=4,
        bgcolor=Colors.AMBER_500,
    )
    status_text = ft.Text("Backend Agent: Connecting...", size=12, color="#CBD5E1")

    header = ft.Container(
        content=ft.Row(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            width=42,
                            height=42,
                            alignment=ft.Alignment.CENTER,
                            bgcolor="#172554",
                            border_radius=BorderRadius.all(13),
                            content=ft.Icon(Icons.SMART_TOY_ROUNDED, color="#60A5FA", size=24),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("Local Agent Studio", size=18, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                                ft.Text("Your workspace for chat, tools and voice", size=11, color="#94A3B8"),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                    ],
                    spacing=12,
                ),
                ft.Row(
                    controls=[
                        ft.Container(
                            padding=Padding.symmetric(horizontal=12, vertical=9),
                            bgcolor="#151D28",
                            border=Border.all(1, "#253246"),
                            border_radius=BorderRadius.all(20),
                            content=ft.Row([status_indicator, status_text], spacing=8, tight=True),
                        ),
                        ft.OutlinedButton(
                            "Reconnect",
                            icon=Icons.REFRESH_ROUNDED,
                            on_click=lambda _: asyncio.create_task(verify_backend_connection()),
                        ),
                    ],
                    spacing=10,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=Padding.symmetric(horizontal=22, vertical=14),
        bgcolor="#0F1722",
        border=Border.only(bottom=ft.BorderSide(1, "#202B3A")),
    )

    # --- Left Sidebar (Discovered Tools & Status) ---
    tool_list_items = [
        ft.Container(
            padding=Padding.all(11),
            bgcolor="#151D28",
            border=Border.all(1, "#202B3A"),
            border_radius=BorderRadius.all(12),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=32,
                        height=32,
                        alignment=ft.Alignment.CENTER,
                        bgcolor="#172554",
                        border_radius=BorderRadius.all(10),
                        content=ft.Icon(Icons.BUILD_CIRCLE_ROUNDED, size=17, color="#60A5FA"),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(tool.name.replace("_", " "), size=11, weight=ft.FontWeight.BOLD, color="#E2E8F0"),
                            ft.Text(tool.description, size=10, color="#94A3B8"),
                        ],
                        spacing=3,
                        tight=True,
                        expand=True,
                    ),
                ],
                spacing=9,
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        ) for tool in ALL_TOOLS
    ]

    sidebar = ft.Container(
        width=sidebar_width,
        visible=show_sidebar,
        padding=Padding.all(16),
        bgcolor="#0F1722",
        border=Border.all(1, "#202B3A"),
        border_radius=BorderRadius.all(18),
        content=ft.Column(
            controls=[
                ft.Text("WORKSPACE", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                ft.Text("Agent overview", size=17, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                ft.Container(
                    padding=Padding.all(13),
                    bgcolor="#151D28",
                    border=Border.all(1, "#202B3A"),
                    border_radius=BorderRadius.all(13),
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Icon(Icons.AUTO_AWESOME, color="#34D399", size=17),
                                    ft.Text("LangGraph Engine", size=12, weight=ft.FontWeight.BOLD, color="#E2E8F0"),
                                ],
                                spacing=8,
                            ),
                            ft.Text("Ready to handle your requests", size=10, color="#94A3B8"),
                        ],
                        spacing=7,
                        tight=True,
                    ),
                ),
                ft.Row(
                    controls=[
                        ft.Text("AVAILABLE TOOLS", size=10, weight=ft.FontWeight.BOLD, color="#64748B"),
                        ft.Container(expand=True),
                        ft.Container(
                            padding=Padding.symmetric(horizontal=8, vertical=3),
                            bgcolor="#172554",
                            border_radius=BorderRadius.all(12),
                            content=ft.Text(str(len(ALL_TOOLS)), size=10, weight=ft.FontWeight.BOLD, color="#93C5FD"),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.ListView(expand=True, spacing=8, controls=tool_list_items),
            ],
            spacing=13,
            expand=True,
        ),
    )

    # --- Main Chat Area ---
    input_field = ft.TextField(
        hint_text="Message your agent...",
        expand=True,
        border={
            ft.ControlState.DEFAULT: ft.OutlineInputBorder(
                border_radius=BorderRadius.all(8),
                side=ft.BorderSide(color="#334155"),
            ),
            ft.ControlState.FOCUSED: ft.OutlineInputBorder(
                border_radius=BorderRadius.all(8),
                side=ft.BorderSide(color="#60A5FA", width=1.5),
            ),
        },
        cursor_color="#60A5FA",
        text_size=14,
        color="#F8FAFC",
        hint_style=ft.TextStyle(color="#64748B", size=13),
        content_padding=Padding.symmetric(horizontal=12, vertical=12),
        shift_enter=True,
        min_lines=1,
        max_lines=4
    )

    async def submit_message(user_msg: str):
        chat_list.controls.append(create_chat_bubble(user_msg, "user"))
        page.update()
        asyncio.create_task(run_agent_stream(user_msg, log_mcp_event, add_agent_message))

    async def send_message_click(e):
        if not input_field.value.strip():
            return
        
        user_msg = input_field.value.strip()
        input_field.value = ""
        await submit_message(user_msg)

    async def voice_message_click(e):
        nonlocal recording_stream

        if recording_stream is None:
            def capture_audio(indata, frames, time_info, status):
                recording_frames.append(bytes(indata))
                if status:
                    recording_errors.append(str(status))

            try:
                recording_frames.clear()
                recording_errors.clear()
                recording_stream = sd.RawInputStream(
                    samplerate=16000,
                    channels=1,
                    dtype="int16",
                    callback=capture_audio,
                )
                recording_stream.start()
                voice_button.icon = Icons.STOP_CIRCLE_ROUNDED
                voice_button.tooltip = "Stop recording and send"
                voice_status.value = "Recording voice message..."
                await log_mcp_event("Voice recording started.", "INFO")
                page.update()
            except Exception as exc:
                recording_stream = None
                voice_status.value = "Microphone unavailable"
                await log_mcp_event(
                    f"Could not start recording ({type(exc).__name__}). Check microphone access and input device.",
                    "ERROR",
                )
                page.update()
            return

        stream = recording_stream
        recording_stream = None
        try:
            stream.stop()
            stream.close()
            audio_data = b"".join(recording_frames)
            recording_frames.clear()
            if recording_errors:
                await log_mcp_event("Audio capture reported a microphone error.", "ERROR")
                voice_status.value = "Microphone capture failed"
                await add_agent_message(
                    "I couldn't record that voice message. Check microphone access and try again."
                )
                return
            if not audio_data:
                await log_mcp_event("No audio was captured; the agent was not called.", "ERROR")
                voice_status.value = "No audio captured"
                await add_agent_message(
                    "I couldn't hear any audio. Check your microphone and try recording again."
                )
                return
            if len(audio_data) < 16000:
                await log_mcp_event("Recording was shorter than 0.5 seconds; the agent was not called.", "INFO")
                voice_status.value = "Recording too short"
                await add_agent_message(
                    "That recording was too short to transcribe. Hold the microphone button while speaking, "
                    "then press it again to send."
                )
                return

            voice_button.disabled = True
            voice_status.value = "Transcribing locally..."
            await log_mcp_event(
                "Recording stopped; transcribing locally. The first run may download the Whisper model.",
                "INFO",
            )
            page.update()

            recording_path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(recording_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(audio_data)
            transcript_text = await asyncio.to_thread(transcribe_audio, recording_path)
            if not transcript_text:
                await log_mcp_event("No clear speech was detected; the agent was not called.", "INFO")
                voice_status.value = "No clear speech detected"
                await add_agent_message(
                    "I couldn't clearly understand that voice message. Please speak clearly and try again."
                )
                return

            await log_mcp_event("Voice message transcribed and sent to the agent.", "SUCCESS")
            voice_status.value = ""
            await submit_message(transcript_text)
        except Exception as exc:
            voice_status.value = f"Voice transcription failed ({type(exc).__name__})"
            await log_mcp_event(
                f"Local transcription failed ({type(exc).__name__}): {exc}. The agent was not called.",
                "ERROR",
            )
            await add_agent_message(
                f"I couldn't transcribe that voice message locally ({type(exc).__name__}: {exc}). "
                "The agent was not called."
            )
        finally:
            voice_button.disabled = False
            voice_button.icon = Icons.MIC_ROUNDED
            voice_button.tooltip = "Record a voice message"
            page.update()

    send_button = ft.IconButton(
        icon=Icons.SEND_ROUNDED,
        icon_color="#FFFFFF",
        bgcolor="#2563EB",
        tooltip="Send message",
        icon_size=20,
        on_click=send_message_click
    )
    voice_button = ft.IconButton(
        icon=Icons.MIC_ROUNDED,
        icon_color="#93C5FD",
        bgcolor="#172554",
        tooltip="Record a voice message",
        on_click=voice_message_click,
    )
    voice_status = ft.Text("", size=12, color=WHITE_70)

    input_container = ft.Container(
        padding=Padding.symmetric(horizontal=12, vertical=8),
        bgcolor="#111B28",
        border=Border.all(1, "#2B394C"),
        border_radius=BorderRadius.all(16),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[input_field, voice_button, send_button],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                voice_status,
            ],
            spacing=2,
        ),
    )

    chat_section = ft.Container(
        expand=1,
        padding=Padding.all(16),
        bgcolor="#0F1722",
        border=Border.all(1, "#202B3A"),
        border_radius=BorderRadius.all(18),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Column(
                            controls=[
                                ft.Text("Conversation", size=17, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                                ft.Text("Send a message or record your voice", size=11, color="#94A3B8"),
                            ],
                            spacing=3,
                            tight=True,
                        ),
                        ft.Container(expand=True),
                        ft.Container(
                            padding=Padding.symmetric(horizontal=10, vertical=6),
                            bgcolor="#102820",
                            border_radius=BorderRadius.all(14),
                            content=ft.Row(
                                controls=[
                                    ft.Container(width=7, height=7, border_radius=4, bgcolor="#34D399"),
                                    ft.Text("Local voice", size=10, color="#A7F3D0"),
                                ],
                                spacing=6,
                                tight=True,
                            ),
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Divider(height=1, color="#202B3A"),
                chat_list,
                input_container,
            ],
            spacing=12,
            expand=True,
        ),
    )

    # --- Right Terminal / Log Panel ---
    log_panel = ft.Container(
        width=log_panel_width,
        visible=show_activity,
        padding=Padding.all(14),
        bgcolor="#0F1722",
        border=Border.all(1, "#202B3A"),
        border_radius=BorderRadius.all(18),
        content=ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Container(
                            width=32,
                            height=32,
                            alignment=ft.Alignment.CENTER,
                            bgcolor="#172554",
                            border_radius=BorderRadius.all(10),
                            content=ft.Icon(Icons.TERMINAL_ROUNDED, size=16, color="#60A5FA"),
                        ),
                        ft.Column(
                            controls=[
                                ft.Text("Activity", size=14, weight=ft.FontWeight.BOLD, color="#F8FAFC"),
                                ft.Text("Recent agent events", size=10, color="#94A3B8"),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                    ],
                    spacing=9,
                ),
                ft.Divider(height=1, color="#202B3A"),
                mcp_logs,
            ],
            spacing=10,
            expand=True,
        ),
    )

    # --- Connection Check Handler ---
    async def verify_backend_connection():
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key and not api_key.startswith("sk-proj-your_actual"):
            status_indicator.bgcolor = Colors.AMBER_500
            status_text.value = "OpenAI API key configured"
            await log_mcp_event(
                "OPENAI_API_KEY is configured; it will be validated when a request is sent.",
                "INFO",
            )
        else:
            status_indicator.bgcolor = Colors.RED_500
            status_text.value = "Backend Agent: API Key Missing"
            await log_mcp_event("Error: Valid OPENAI_API_KEY missing in .env file.", "ERROR")
        page.update()

    def handle_page_resize(event: ft.PageResizeEvent):
        nonlocal chat_row_width, bubble_width, log_panel_width

        viewport_width = event.width
        show_sidebar = viewport_width > 1120
        show_activity = viewport_width > 820
        log_panel_width = 300 if viewport_width > 1120 else 260
        sidebar.visible = show_sidebar
        log_panel.visible = show_activity
        log_panel.width = log_panel_width

        chat_row_width = max(
            240,
            viewport_width
            - 32
            - 28
            - (sidebar_width if show_sidebar else 0)
            - (log_panel_width if show_activity else 0)
            - 32,
        )
        bubble_width = max(220, min(620, chat_row_width * 0.88))
        for chat_row, bubble in chat_bubbles:
            chat_row.width = chat_row_width
            bubble.width = bubble_width
        for log_card in log_cards:
            log_card.width = log_panel_width - 56
        page.update()

    page.on_resize = handle_page_resize

    # --- Page Assembly ---
    main_layout = ft.Row(
        controls=[sidebar, chat_section, log_panel],
        expand=True,
        spacing=14,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    page.add(
        header,
        ft.Container(
            expand=True,
            padding=Padding.all(16),
            content=main_layout,
        ),
    )
    
    # Auto-initialize backend status on app launch
    await verify_backend_connection()

if __name__ == "__main__":
    ft.run(main)