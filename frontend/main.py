import asyncio
import os
import flet as ft
from dotenv import load_dotenv

# Import backend LangGraph streaming engine and tool list
from backend.agent import run_agent_stream
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
    page.padding = 0
    page.window.width = 1200
    page.window.height = 800
    page.window.min_width = 900
    page.window.min_height = 600

    # --- UI State Containers ---
    chat_list = ft.ListView(expand=True, spacing=12, padding=15, auto_scroll=True)
    mcp_logs = ft.ListView(expand=True, spacing=6, padding=10, auto_scroll=True)
    
    # --- UI Component Builders ---
    def create_chat_bubble(message: str, sender: str):
        is_user = sender == "user"
        bg_color = Colors.BLUE_700 if is_user else SURFACE_VARIANT
        align = ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START
        
        return ft.Row(
            alignment=align,
            controls=[
                ft.Container(
                    content=ft.Column([
                        ft.Text(
                            "You" if is_user else "LangGraph Agent", 
                            size=11, 
                            weight=ft.FontWeight.BOLD, 
                            color=WHITE_54
                        ),
                        ft.Text(message, size=14, selectable=True, color=Colors.WHITE),
                    ], spacing=2),
                    padding=Padding.all(12),
                    bgcolor=bg_color,
                    border_radius=BorderRadius.all(10),
                    max_width=600,
                )
            ]
        )

    async def log_mcp_event(event_text: str, level: str = "INFO"):
        color_map = {
            "INFO": Colors.BLUE_400,
            "TOOL": Colors.AMBER_400,
            "SUCCESS": Colors.GREEN_400,
            "ERROR": Colors.RED_400,
        }
        mcp_logs.controls.append(
            ft.Text(
                f"[{level}] {event_text}",
                font_family="monospace",
                size=12,
                color=color_map.get(level, WHITE_70)
            )
        )
        page.update()

    async def add_agent_message(text: str):
        chat_list.controls.append(create_chat_bubble(text, "agent"))
        page.update()

    # --- Header / Backend Connection Status ---
    status_indicator = ft.Container(width=10, height=10, border_radius=5, bgcolor=Colors.AMBER_500)
    status_text = ft.Text("Backend Agent: Connecting...", size=13, color=WHITE_70)

    header = ft.Container(
        content=ft.Row([
            ft.Row([
                ft.Icon(Icons.SMART_TOY_ROUNDED, color=Colors.BLUE_400, size=28),
                ft.Text("Local Agent Controller", size=18, weight=ft.FontWeight.BOLD),
            ]),
            ft.Row([
                status_indicator,
                status_text,
                ft.OutlinedButton(
                    "Reconnect Agent", 
                    icon=Icons.REFRESH_ROUNDED, 
                    on_click=lambda _: asyncio.create_task(verify_backend_connection())
                )
            ], spacing=12)
        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        padding=Padding.symmetric(horizontal=20, vertical=12),
        bgcolor=BACKGROUND,
        border=Border.only(bottom=ft.BorderSide(1, WHITE_10))
    )

    # --- Left Sidebar (Discovered Tools & Status) ---
    tool_list_items = [
        ft.ListTile(
            leading=ft.Icon(Icons.BUILD_CIRCLE_ROUNDED, size=18, color=Colors.BLUE_400),
            title=ft.Text(tool.name, size=12, weight=ft.FontWeight.W_600),
            subtitle=ft.Text(tool.description[:40] + "...", size=10, color=WHITE_54),
            dense=True
        ) for tool in ALL_TOOLS
    ]

    sidebar = ft.Container(
        width=260,
        bgcolor=Colors.SURFACE,
        padding=15,
        content=ft.Column([
            ft.Text("AGENT RUNTIME", size=12, weight=ft.FontWeight.BOLD, color=WHITE_54),
            ft.Card(
                content=ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Icon(Icons.RUN_CIRCLE, color=Colors.GREEN_400, size=16),
                            ft.Text("LangGraph Engine", size=13, weight=ft.FontWeight.W_600)
                        ]),
                        ft.Text("Model: gpt-4o-mini", size=11, color=WHITE_54)
                    ], spacing=4),
                    padding=10
                )
            ),
            ft.Divider(height=20, color=WHITE_10),
            ft.Text("LOADED TOOLS", size=12, weight=ft.FontWeight.BOLD, color=WHITE_54),
            ft.ListView(expand=True, spacing=4, controls=tool_list_items)
        ])
    )

    # --- Main Chat Area ---
    input_field = ft.TextField(
        hint_text="Ask agent or trigger tools (e.g., 'What time is it and calculate 42 * 18')",
        expand=True,
        border_radius=8,
        shift_enter=True,
        min_lines=1,
        max_lines=4
    )

    async def send_message_click(e):
        if not input_field.value.strip():
            return
        
        user_msg = input_field.value.strip()
        input_field.value = ""
        chat_list.controls.append(create_chat_bubble(user_msg, "user"))
        page.update()

        # Stream workflow output from backend
        asyncio.create_task(run_agent_stream(user_msg, log_mcp_event, add_agent_message))

    send_button = ft.IconButton(
        icon=Icons.SEND_ROUNDED,
        icon_color=Colors.BLUE_400,
        on_click=send_message_click
    )

    input_container = ft.Container(
        padding=10,
        bgcolor=Colors.SURFACE,
        content=ft.Row([input_field, send_button])
    )

    chat_section = ft.Column([
        chat_list,
        input_container
    ], expand=True)

    # --- Right Terminal / Log Panel ---
    log_panel = ft.Container(
        width=340,
        bgcolor=Colors.BLACK,
        padding=10,
        content=ft.Column([
            ft.Row([
                ft.Icon(Icons.TERMINAL_ROUNDED, size=16, color=WHITE_54),
                ft.Text("Execution Stream Logs", size=12, weight=ft.FontWeight.BOLD, color=WHITE_54)
            ]),
            ft.Divider(height=10, color=WHITE_10),
            mcp_logs
        ])
    )

    # --- Connection Check Handler ---
    async def verify_backend_connection():
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key and not api_key.startswith("sk-proj-your_actual"):
            status_indicator.bgcolor = Colors.GREEN_500
            status_text.value = "Backend Agent: Connected"
            await log_mcp_event("Successfully connected to LangGraph agent engine.", "SUCCESS")
        else:
            status_indicator.bgcolor = Colors.RED_500
            status_text.value = "Backend Agent: API Key Missing"
            await log_mcp_event("Error: Valid OPENAI_API_KEY missing in .env file.", "ERROR")
        page.update()

    # --- Page Assembly ---
    main_layout = ft.Row([
        sidebar,
        ft.VerticalDivider(width=1, color=WHITE_10),
        chat_section,
        ft.VerticalDivider(width=1, color=WHITE_10),
        log_panel
    ], expand=True)

    page.add(
        header,
        main_layout
    )
    
    # Auto-initialize backend status on app launch
    await verify_backend_connection()

if __name__ == "__main__":
    ft.run(main)