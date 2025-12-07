import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests


@dataclass
class RoutedResult:
    """Simple container for router responses."""

    content: str
    used_tool: Optional[str] = None


class CommandRouter:
    """Send parsed intents to Ollama with tool-calling support."""

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None):
        self.model = model or os.environ.get("OLLAMA_MODEL", "llama3.1")
        self.base_url = base_url or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.persona_prompt = (
            "You are BMO from Adventure Time. You are playful, whimsical, and supportive. "
            "When responding to the user, keep replies concise and in-character while being helpful."
        )
        self.tools = self._build_tools()
        self.tool_handlers = {
            "launch_retroarch_game": self.launch_retroarch_game,
            "launch_application": self.launch_application,
            "system_control": self.system_control,
        }

    def _build_tools(self) -> List[Dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "launch_retroarch_game",
                    "description": (
                        "Launch a ROM in RetroArch. Use this when the user asks to play a specific game or platform."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rom_path": {
                                "type": "string",
                                "description": "Absolute path to the ROM file requested by the user.",
                            },
                            "core_path": {
                                "type": "string",
                                "description": "Optional: path to a specific RetroArch core to load before the ROM.",
                            },
                        },
                        "required": ["rom_path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "launch_application",
                    "description": "Start a desktop or system application with optional arguments.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "Command to execute (e.g. 'spotify', 'vlc --fullscreen').",
                            }
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "system_control",
                    "description": "Perform a system level action like shutdown, reboot, or sleep.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["shutdown", "reboot", "sleep"],
                                "description": "The system action to perform.",
                            }
                        },
                        "required": ["action"],
                    },
                },
            },
        ]

    def route_command(self, user_input: str) -> RoutedResult:
        """Send user input to Ollama and act on any tool calls returned."""

        try:
            chat_response = self._call_ollama_with_tools(user_input)
            message = chat_response.get("message", {})
            tool_calls = message.get("tool_calls") or []

            if tool_calls:
                results: List[str] = []
                for call in tool_calls:
                    result_text = self._execute_tool(call)
                    results.append(result_text)
                return RoutedResult(content="\n".join(results), used_tool=tool_calls[0].get("function", {}).get("name"))

            persona_text = self._persona_completion(user_input)
            return RoutedResult(content=persona_text)
        except Exception as exc:  # pragma: no cover - defensive fallback
            return RoutedResult(content=f"I ran into a glitch handling that: {exc}")

    def _call_ollama_with_tools(self, user_input: str) -> Dict:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a command router. Prefer calling tools when they fit the request.",
                },
                {"role": "user", "content": user_input},
            ],
            "tools": self.tools,
            "stream": False,
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def _persona_completion(self, user_input: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.persona_prompt},
                {"role": "user", "content": user_input},
            ],
            "stream": False,
        }
        response = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=30)
        response.raise_for_status()
        content = response.json().get("message", {}).get("content")
        return content or "BMO is thinking but stayed quiet."

    def _execute_tool(self, tool_call: Dict) -> str:
        function_spec = tool_call.get("function", {})
        name = function_spec.get("name")
        arguments_raw = function_spec.get("arguments")
        try:
            arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else (arguments_raw or {})
        except json.JSONDecodeError:
            arguments = {}

        handler = self.tool_handlers.get(name)
        if not handler:
            return f"I do not have a handler for {name}."

        return handler(**arguments)

    def launch_retroarch_game(self, rom_path: str, core_path: Optional[str] = None) -> str:
        command = ["retroarch"]
        if core_path:
            command.extend(["-L", core_path])
        command.append(rom_path)
        subprocess.Popen(command)
        return f"Launching RetroArch with {os.path.basename(rom_path)}."

    def launch_application(self, command: str) -> str:
        args = shlex.split(command)
        subprocess.Popen(args)
        return f"Launching application: {command}."

    def system_control(self, action: str) -> str:
        if action == "shutdown":
            subprocess.Popen(["sudo", "shutdown", "now"])
            return "Shutting down now."
        if action == "reboot":
            subprocess.Popen(["sudo", "reboot"])
            return "Rebooting now."
        if action == "sleep":
            subprocess.Popen(["systemctl", "suspend"])
            return "Going to sleep."
        return f"Unknown system action: {action}."
