# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Interactive terminal control room for local Orbit applications.

The control room is a presentation layer over Core's existing inspection and lifecycle
contracts. It does not discover or import installed providers on its own. The operator supplies
an explicit trusted ``module:attribute`` target, matching the scriptable CLI.
"""

from __future__ import annotations

import asyncio
import json
import sys
from types import MappingProxyType
from typing import TYPE_CHECKING

from orbit.application import Application
from orbit.cli.app import load_target
from orbit.diagnostics.inspection import inspect_composition
from orbit.plugins.control import ControlResult, RegisteredControlAction
from orbit.runtime import Runtime
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    OptionList,
    RichLog,
    Select,
    Static,
)
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.worker import Worker


_MENU_ACTIONS = (
    ("overview", "Project overview", "Application identity, lifecycle and registered components"),
    ("checks", "Prepare for review", "Validate composition and configuration without startup"),
    (
        "services",
        "Inspect services and routes",
        "Show registered services, routes and dependencies",
    ),
    ("plugins", "Inspect plugins", "Show explicitly registered plugin metadata and capabilities"),
    ("configuration", "Review configuration", "Show the redacted local configuration snapshot"),
    ("tasks", "Inspect tasks and events", "Show bounded local task and event delivery state"),
    ("feed", "Follow Core activity", "Watch health and diagnostics while Core is running"),
    ("server-start", "Start development server", "Run the local Uvicorn development host"),
    (
        "server-stop",
        "Stop development server",
        "Gracefully stop the server started by this control room",
    ),
)


class _ConfirmAction(ModalScreen[bool]):
    """Require an explicit second choice before running a destructive plugin operation."""

    CSS = """
    _ConfirmAction { align: center middle; }
    #confirm-dialog {
        width: 72; height: auto; max-height: 80%; padding: 1 2;
        border: round $warning; background: $surface;
    }
    #confirm-title { text-style: bold; margin-bottom: 1; }
    #confirm-description { height: auto; margin-bottom: 1; }
    #confirm-buttons { height: 3; align-horizontal: right; }
    #confirm-cancel { margin-right: 1; }
    """

    def __init__(self, title: str, description: str) -> None:
        """Store the action text displayed in the confirmation dialog."""
        super().__init__()
        self._action_title = title
        self._description = description

    def compose(self) -> ComposeResult:
        """Present explicit cancel and continue buttons."""
        with Vertical(id="confirm-dialog"):
            title = Text("Confirm: ")
            title.append(self._action_title, style="bold")
            yield Label(title, id="confirm-title")
            yield Static(Text(self._description), id="confirm-description")
            with Horizontal(id="confirm-buttons"):
                yield Button("Cancel", id="confirm-cancel")
                yield Button("Continue", id="confirm-continue", variant="error")

    def on_mount(self) -> None:
        """Default focus to the safe cancel option."""
        self.query_one("#confirm-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Return the operator's explicit choice to the parent screen."""
        self.dismiss(event.button.id == "confirm-continue")


class _ActionInputForm(ModalScreen[dict[str, object] | None]):
    """Collect an action's declared inputs without exposing UI objects to the plugin."""

    CSS = """
    _ActionInputForm { align: center middle; }
    #action-form { width: 76; height: auto; max-height: 90%; padding: 0 2; overflow-y: auto;
        border: round $primary; background: $surface; }
    .field-label { height: auto; margin-top: 0; text-style: bold; }
    .field-description { height: auto; color: $text-muted; }
    #form-error { height: auto; color: $error; }
    #form-buttons { height: 3; align-horizontal: right; margin-top: 0; }
    #form-cancel { margin-right: 1; }
    """

    def __init__(self, action: RegisteredControlAction) -> None:
        """Retain the immutable action schema used to create this form."""
        super().__init__()
        self._action = action.action

    def compose(self) -> ComposeResult:
        """Create one accessible field for each declared primitive input."""
        with Vertical(id="action-form"):
            title = Text(self._action.title, style="bold")
            yield Static(title)
            for field in self._action.inputs:
                yield Label(Text(field.label), classes="field-label")
                if field.description:
                    yield Static(Text(field.description), classes="field-description")
                field_id = f"action-input-{field.id}"
                if field.kind == "boolean":
                    yield Checkbox(
                        label=field.label,
                        value=bool(field.default) if field.default is not None else False,
                        id=field_id,
                    )
                elif field.kind == "choice":
                    choices = tuple((choice, choice) for choice in field.choices)
                    yield Select(
                        choices,
                        value=field.default if isinstance(field.default, str) else Select.BLANK,
                        allow_blank=not field.required,
                        id=field_id,
                    )
                else:
                    value = "" if field.default is None else str(field.default)
                    yield Input(
                        value=value,
                        placeholder=(
                            f"Enter {field.label.lower()}" if field.required else "Optional"
                        ),
                        max_length=32 if field.kind == "integer" else field.max_length,
                        password=field.kind == "secret",
                        id=field_id,
                    )
            yield Static("", id="form-error")
            with Horizontal(id="form-buttons"):
                yield Button("Cancel", id="form-cancel")
                yield Button("Continue", id="form-continue", variant="primary")

    def on_mount(self) -> None:
        """Focus the first editable field, or the safe Cancel button for empty schemas."""
        fields = self.query("Input, Checkbox, Select")
        (fields.first() if fields else self.query_one("#form-cancel", Button)).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Validate collected primitive values and return them to the action dispatcher."""
        if event.button.id == "form-cancel":
            self.dismiss(None)
            return
        values: dict[str, object] = {}
        try:
            for field in self._action.inputs:
                widget_id = f"#action-input-{field.id}"
                if field.kind == "boolean":
                    value: object = self.query_one(widget_id, Checkbox).value
                elif field.kind == "choice":
                    selected = self.query_one(widget_id, Select).value
                    value = None if selected is Select.BLANK else selected
                else:
                    raw = self.query_one(widget_id, Input).value
                    if raw == "" and not field.required:
                        value = None
                    elif raw == "" and field.required:
                        raise ValueError(f"{field.label} is required.")
                    elif field.kind == "integer":
                        value = int(raw)
                        if len(raw.lstrip("+-")) > 30:
                            raise ValueError(f"{field.label} exceeds the supported integer range.")
                    else:
                        value = raw
                if field.required and value is None:
                    raise ValueError(f"{field.label} is required.")
                values[field.id] = value
        except ValueError as exc:
            self.query_one("#form-error", Static).update(Text(str(exc)))
            return
        self.dismiss(values)


class OrbitControlRoom(App[None]):
    """Keyboard and mouse driven local control room for an explicitly selected application."""

    TITLE = "Orbit Control Room"
    SUB_TITLE = "One interface for your Orbit project"
    CSS = """
    Screen { padding: 1 2; }
    #intro { height: auto; margin-bottom: 1; }
    #target-row { height: 3; }
    #target { width: 1fr; }
    #open { width: 20; margin-left: 1; }
    #status { height: auto; min-height: 2; margin: 1 0; }
    #workspace { height: 1fr; display: none; }
    #actions { width: 42%; min-width: 32; border: round $primary; }
    #feed { width: 1fr; border: round $primary; margin-left: 1; }
    #hint { height: auto; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("escape", "clear_output", "Clear output"),
    ]

    def __init__(self, target: str | None = None) -> None:
        """Create the UI, optionally pre-filling an explicit local application target."""
        super().__init__()
        self._initial_target = target or ""
        self._target_text: str | None = None
        self._application: Application | None = None
        self._server: asyncio.subprocess.Process | None = None
        self._server_reader: Worker[None] | None = None
        self._activity_worker: Worker[None] | None = None
        self._closing = False

    def compose(self) -> ComposeResult:
        """Build the project picker and the persistent action/feed workspace."""
        yield Header()
        with Vertical():
            yield Static(
                "Choose a local Orbit application to inspect and control.\n"
                "Target format: [bold]module:attribute[/bold] (for example, "
                "[dim]examples.minimal.app:application[/dim]). Importing it runs trusted "
                "local code.",
                id="intro",
            )
            with Horizontal(id="target-row"):
                yield Input(
                    placeholder="module:attribute",
                    value=self._initial_target,
                    id="target",
                    validators=None,
                )
                yield Button("Open project", id="open", variant="primary")
            yield Static("No project loaded.", id="status")
            with Horizontal(id="workspace"):
                yield OptionList(
                    *(
                        Option(_menu_label(title, description), id=key)
                        for key, title, description in _MENU_ACTIONS
                    ),
                    id="actions",
                )
                yield RichLog(
                    id="feed",
                    wrap=True,
                    markup=False,
                    max_lines=1_500,
                    highlight=False,
                    auto_scroll=True,
                )
            yield Static(
                "Navigate with ↑/↓, choose with Enter, click menu items, or follow the footer "
                "keys.",
                id="hint",
            )
        yield Footer()

    async def on_mount(self) -> None:
        """Focus the target field and load a target supplied by the caller, if any."""
        self.query_one("#target", Input).focus()
        if self._initial_target:
            await self._open_project()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Open the project when the operator activates the picker button."""
        if event.button.id == "open":
            await self._open_project()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Allow Enter in the target field to open the project directly."""
        if event.input.id == "target":
            await self._open_project()

    async def _open_project(self) -> None:
        """Load the explicit local application and show its available Core actions."""
        target = self.query_one("#target", Input).value.strip()
        status = self.query_one("#status", Static)
        if not target:
            status.update("Enter a local application target to continue.")
            self.query_one("#target", Input).focus()
            return
        status.update("Loading the selected local application…")
        try:
            value = load_target(target)
        except Exception as exc:
            # load_target normalizes import errors, but keep this UI boundary bounded as well.
            status.update(
                f"Could not open project ({type(exc).__name__}). Check the target and local logs."
            )
            return
        self._application = value.application if isinstance(value, Runtime) else value
        self._target_text = target
        app = self._application
        status_text = Text()
        status_text.append(app.config.application.name, style="bold")
        status_text.append(
            f" · {len(app.services.descriptors)} services · "
            f"{len(app.plugins.plugins)} plugins · phase: {app.lifecycle.phase.value}"
        )
        status.update(status_text)
        self.query_one("#workspace").styles.display = "block"
        enabled_plugins = set(app.plugins.enabled_names)
        actions = self.query_one("#actions", OptionList)
        for registered in app.control_actions.actions:
            if registered.plugin_name in enabled_plugins:
                actions.add_option(
                    Option(
                        _menu_label(
                            registered.action.title,
                            f"{registered.plugin_name} · {registered.action.description}",
                        ),
                        id=f"plugin-action:{registered.key}",
                    )
                )
        self.query_one("#actions", OptionList).focus()
        self._write(
            "Project loaded. Select an action. Inspection reads only the explicitly composed local "
            "application; it does not query a remote deployment."
        )

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dispatch a selected menu action to the corresponding Core contract."""
        action = event.option.id
        if not isinstance(action, str) or self._application is None:
            return
        if action.startswith("plugin-action:"):
            self.run_worker(
                self._run_plugin_action(action.removeprefix("plugin-action:")),
                name="orbit-plugin-control-action",
                group="plugin-actions",
                exclusive=False,
                exit_on_error=False,
            )
            return
        handlers = {
            "overview": self._show_overview,
            "checks": self._prepare_review,
            "services": self._show_services,
            "plugins": self._show_plugins,
            "configuration": self._show_configuration,
            "tasks": self._show_tasks_and_events,
            "feed": self._toggle_activity_feed,
            "server-start": self._start_server,
            "server-stop": self._stop_server,
        }
        handler = handlers.get(action)
        if handler is not None:
            await handler()

    async def _run_plugin_action(self, key: str) -> None:
        """Run one registered plugin action after confirmation when it changes state."""
        assert self._application is not None
        registered = next(
            (item for item in self._application.control_actions.actions if item.key == key), None
        )
        if (
            registered is None
            or registered.plugin_name not in self._application.plugins.enabled_names
        ):
            self._write("That plugin action is no longer available.")
            return
        action = registered.action
        if action.destructive:
            confirmed = await self.push_screen_wait(
                _ConfirmAction(action.title, action.description)
            )
            if not confirmed:
                self._write(f"Cancelled: {action.title}.")
                return
        if action.inputs:
            self.push_screen(
                _ActionInputForm(registered),
                callback=lambda selected: self._on_action_inputs(registered, selected),
            )
            return
        await self._execute_plugin_action(registered, {})

    def _on_action_inputs(
        self, registered: RegisteredControlAction, values: dict[str, object] | None
    ) -> None:
        """Dispatch validated modal results to an independently supervised async action."""
        if values is None:
            self._write(f"Cancelled: {registered.action.title}.")
            return
        self.run_worker(
            self._execute_plugin_action(registered, values),
            name=f"orbit-plugin-action-{registered.action.id}",
            group="plugin-actions",
            exclusive=False,
            exit_on_error=False,
        )

    async def _execute_plugin_action(
        self, registered: RegisteredControlAction, values: dict[str, object]
    ) -> None:
        """Invoke the selected plugin callback and render only its bounded safe result."""
        action = registered.action
        self._write(f"Running {registered.plugin_name}: {action.title}…")
        try:
            result = await action.handler(MappingProxyType(dict(values)))
        except Exception as exc:
            # Do not print provider exception text; it can contain credentials or request data.
            self._write(f"Action failed ({type(exc).__name__}). Check the plugin's redacted logs.")
            return
        if result is not None and not isinstance(result, ControlResult):
            self._write("Action returned an invalid result. Check the plugin's redacted logs.")
            return
        if result is None:
            self._write(f"Completed: {action.title}.")
        else:
            prefix = "Completed" if result.succeeded else "Action reported a problem"
            self._write("\n".join((f"{prefix}: {result.summary}", *result.details)))

    async def _show_overview(self) -> None:
        """Display bounded local state and composition counts."""
        assert self._application is not None
        application = self._application
        self._write(
            json.dumps(
                {
                    "application": application.config.application.name,
                    "environment": application.config.application.environment,
                    "phase": application.lifecycle.phase.value,
                    "live": application.is_live,
                    "ready": application.is_ready,
                    "services": len(application.services.descriptors),
                    "plugins": len(application.plugins.plugins),
                    "routes": len(application.router.routes),
                },
                indent=2,
            )
        )

    async def _prepare_review(self) -> None:
        """Run the non-invasive validations used before a local review session."""
        assert self._application is not None
        application = self._application
        checks: dict[str, str] = {}
        try:
            application.validate()
            checks["composition"] = "passed"
        except Exception as exc:
            checks["composition"] = f"failed ({type(exc).__name__})"
        try:
            application.config.inspect()
            checks["configuration"] = "passed"
        except Exception as exc:
            checks["configuration"] = f"failed ({type(exc).__name__})"
        checks["registered_services"] = str(len(application.services.descriptors))
        checks["registered_plugins"] = str(len(application.plugins.plugins))
        self._write(json.dumps(checks, indent=2))

    async def _show_services(self) -> None:
        """Display registered service, route and dependency metadata."""
        self._show_section("services", "routes", "dependencies")

    async def _show_plugins(self) -> None:
        """Display metadata for plugins explicitly registered by the application."""
        self._show_section("plugins")

    async def _show_configuration(self) -> None:
        """Display configuration through Core's redacted inspection snapshot."""
        self._show_section("configuration")

    def _show_section(self, *sections: str) -> None:
        """Render selected sections from Core's detached composition inspection."""
        assert self._application is not None
        snapshot = inspect_composition(self._application).model_dump(mode="json")
        self._write(json.dumps({key: snapshot[key] for key in sections}, indent=2))

    async def _show_tasks_and_events(self) -> None:
        """Show bounded task failure metadata and payload-free event delivery history."""
        assert self._application is not None
        application = self._application
        self._write(
            json.dumps(
                {
                    "tasks": [
                        {
                            "name": item.name,
                            "state": str(item.state),
                            "attempts": item.attempts,
                            "last_failure_type": (
                                item.last_failure.error_type if item.last_failure else None
                            ),
                        }
                        for item in application.tasks.infos
                    ],
                    "events": [
                        {
                            "id": str(item.event_id),
                            "name": item.name,
                            "subscribers": item.subscriber_count,
                            "failures": item.failures,
                            "deduplicated": item.deduplicated,
                        }
                        for item in application.events.history
                    ],
                },
                indent=2,
            )
        )

    async def _toggle_activity_feed(self) -> None:
        """Start or stop a bounded Core health/diagnostics feed."""
        if self._activity_worker is not None and self._activity_worker.is_running:
            self._activity_worker.cancel()
            self._activity_worker = None
            return
        if self._application is None or self._application.lifecycle.phase.value != "created":
            self._write(
                "Core lifecycle has already been used; load a fresh process to start another feed."
            )
            return
        self._activity_worker = self.run_worker(
            self._follow_activity(),
            name="orbit-core-activity-feed",
            group="control-room",
            exit_on_error=False,
        )

    async def _follow_activity(self) -> None:
        """Own one application lifecycle while periodically sampling safe Core diagnostics."""
        assert self._application is not None
        application = self._application
        self._write(
            "Starting Core lifecycle. Feed shows Core health and diagnostics; it is not a log tail."
        )
        try:
            async with application.running():
                while not self._closing:
                    health = await application.health()
                    snapshot = application.diagnostics.collect(application)
                    self._write(
                        f"health={health.status.value} phase={application.lifecycle.phase} "
                        f"ready={application.is_ready}\n"
                        f"diagnostics={snapshot.model_dump_json()}"
                    )
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._write(
                f"Core activity feed stopped ({type(exc).__name__}). Check application logs."
            )
        finally:
            self._activity_worker = None

    async def _start_server(self) -> None:
        """Launch the existing Uvicorn development command as a supervised child process."""
        if self._server is not None and self._server.returncode is None:
            self._write("Development server is already running in this control room.")
            return
        assert self._application is not None
        if self._target_text is None:
            return
        try:
            value = load_target(self._target_text)
        except Exception as exc:
            self._write(f"Could not reload the project ({type(exc).__name__}).")
            return
        if not isinstance(value, Runtime):
            self._write("The development server needs a Runtime target, for example app:runtime.")
            return
        self._server = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "orbit.cli",
            "serve",
            self._target_text,
            "--server",
            "uvicorn",
            "--reload",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._write("Starting Uvicorn with source reload on 127.0.0.1:8000…")
        self._server_reader = self.run_worker(
            self._read_server_output(),
            name="orbit-server-output",
            group="control-room",
            exit_on_error=False,
        )

    async def _read_server_output(self) -> None:
        """Stream a bounded amount of child process output into the visible activity panel."""
        process = self._server
        if process is None or process.stdout is None:
            return
        while line := await process.stdout.readline():
            self._write(line.decode("utf-8", errors="replace").rstrip()[:2_000])
        code = await process.wait()
        self._write(f"Development server exited with status {code}.")

    async def _stop_server(self) -> None:
        """Ask the managed development server to stop, then enforce a bounded wait."""
        process = self._server
        if process is None or process.returncode is not None:
            self._write("No development server is running in this control room.")
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10.0)
        except TimeoutError:
            process.kill()
            await process.wait()
        self._write("Development server stopped.")

    def _write(self, message: str) -> None:
        """Append plain text to the bounded output panel without interpreting markup."""
        self.query_one("#feed", RichLog).write(Text(message))

    def action_clear_output(self) -> None:
        """Clear the visible feed without changing project or lifecycle state."""
        self.query_one("#feed", RichLog).clear()

    async def on_unmount(self) -> None:
        """Stop child processes and cancel lifecycle feeds when leaving the control room."""
        self._closing = True
        if self._activity_worker is not None and self._activity_worker.is_running:
            self._activity_worker.cancel()
        process = self._server
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except TimeoutError:
                process.kill()
                await process.wait()


def run_control_room(target: str | None = None) -> None:
    """Run the interactive local control room until the operator exits."""
    OrbitControlRoom(target=target).run()


def _menu_label(title: str, description: str) -> Text:
    """Build a menu label with plain text metadata and fixed presentation styles."""
    label = Text(title)
    label.append("\n")
    label.append(description, style="dim")
    return label


__all__ = ["OrbitControlRoom", "run_control_room"]
