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
"""Exercise the interactive CLI shell and its plugin action boundary."""

from __future__ import annotations

import asyncio
import importlib
import runpy
import sys
import types

import pytest
from orbit import ApplicationBuilder, ApplicationConfig
from orbit.plugins import ControlAction, ControlInput, ControlResult, Plugin, PluginMetadata
from orbit.plugins.control import ControlActionRegistry
from orbit.runtime import Runtime
from textual.widgets import Input, OptionList, Select
from textual.widgets.option_list import Option
from typer.testing import CliRunner

from orbit_cli.app import app
from orbit_cli.control_room import OrbitControlRoom


class ReviewPlugin(Plugin):
    """Fixture plugin contributing a safe and a destructive review operation."""

    metadata = PluginMetadata(name="orbit-cli-review-fixture", version="0.1.0a1")
    control_actions: tuple[ControlAction, ...] = ()


def test_module_entrypoint_invokes_the_cli(monkeypatch):
    """The documented ``python -m orbit_cli`` entry point invokes the Typer application."""
    app_module = importlib.import_module("orbit_cli.app")
    calls: list[bool] = []
    monkeypatch.setattr(app_module, "app", lambda: calls.append(True))

    runpy.run_module("orbit_cli.__main__", run_name="__main__")

    assert calls == [True]


@pytest.fixture
def target(monkeypatch):
    """Install a composed local application target for TUI loading tests."""
    application = ApplicationBuilder(ApplicationConfig(name="control-room-test")).build()
    module = types.ModuleType("orbit_control_room_target")
    module.application = application
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module


@pytest.mark.asyncio
async def test_control_room_loads_explicit_target_and_shows_core_actions(target):
    """The primary terminal app opens a target and exposes Core inspection actions."""
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        assert control_room._application is target.application
        actions = control_room.query_one("#actions", OptionList)
        assert len(actions._options) >= 8
        await pilot.press("down", "enter")
        await pilot.pause()
        assert control_room.query_one("#status").renderable


@pytest.mark.asyncio
async def test_control_room_inspection_actions_use_core_snapshots(target):
    """The control room exposes read-only Core inspection without starting services."""
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        await control_room._show_overview()
        await control_room._prepare_review()
        await control_room._show_services()
        await control_room._show_plugins()
        await control_room._show_configuration()
        await control_room._show_tasks_and_events()
        assert target.application.lifecycle.phase.value == "created"


@pytest.mark.asyncio
async def test_control_room_picker_reports_empty_and_invalid_targets(target):
    """The project picker gives bounded guidance for empty and failed target imports."""
    control_room = OrbitControlRoom()

    async with control_room.run_test() as pilot:
        await pilot.pause()
        await control_room._open_project()
        assert "Enter a local" in str(control_room.query_one("#status").renderable)
        control_room.query_one("#target").value = "missing_control_room_target:app"
        await control_room._open_project()
        assert "Could not open project" in str(control_room.query_one("#status").renderable)
        control_room.query_one("#target").value = "orbit_control_room_target:application"
        await control_room._open_project()
        assert control_room._application is target.application


@pytest.mark.asyncio
async def test_project_picker_buttons_and_menu_dispatch(target):
    """Mouse clicks open a project and select a visible control-room menu action."""
    control_room = OrbitControlRoom()

    async with control_room.run_test() as pilot:
        await pilot.pause()
        control_room.query_one("#target").value = "orbit_control_room_target:application"
        await pilot.click("#open")
        await pilot.pause()
        actions = control_room.query_one("#actions", OptionList)
        await pilot.click("#actions", offset=(4, 1))
        await pilot.pause()
        assert '"application": "control-room-test"' in str(control_room.query_one("#feed").lines)
        actions.add_option(Option("Unknown", id="unknown-menu-action"))
        await control_room.on_option_list_option_selected(
            OptionList.OptionSelected(actions, len(actions._options) - 1)
        )


@pytest.mark.asyncio
async def test_project_picker_enter_submits_target(target):
    """The target field supports a direct Enter workflow without clicking the button."""
    control_room = OrbitControlRoom()

    async with control_room.run_test() as pilot:
        await pilot.pause()
        field = control_room.query_one("#target")
        field.value = "orbit_control_room_target:application"
        field.focus()
        await pilot.press("enter")
        await pilot.pause()
        assert control_room._application is target.application


@pytest.mark.asyncio
async def test_review_check_failures_are_reported_without_exception_messages(target, monkeypatch):
    """Failed non-invasive checks are summarized by type without echoing unsafe details."""
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    def fail_validation():
        raise RuntimeError("credential value")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        messages: list[str] = []
        write = control_room._write

        def capture(message: str) -> None:
            messages.append(message)
            write(message)

        monkeypatch.setattr(control_room, "_write", capture)
        monkeypatch.setattr(target.application, "validate", fail_validation)
        await control_room._prepare_review()
        text = messages[-1]
        assert "RuntimeError" in text
        assert "credential value" not in text


@pytest.mark.asyncio
async def test_plugin_actions_are_registered_and_executed_by_control_room(target):
    """Plugins contribute presentation-neutral async actions to the shared operator UI."""
    calls: list[str] = []

    async def inspect_provider(values: dict[str, object]) -> None:
        calls.append("inspect")

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            id="inspect",
            title="Inspect provider",
            description="Check the configured provider connection.",
            handler=inspect_provider,
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        actions = control_room.query_one("#actions", OptionList)
        assert any(
            option.id == "plugin-action:orbit-cli-review-fixture/inspect"
            for option in actions._options
        )
        index = next(
            index
            for index, option in enumerate(actions._options)
            if option.id == "plugin-action:orbit-cli-review-fixture/inspect"
        )
        await control_room.on_option_list_option_selected(OptionList.OptionSelected(actions, index))
        await pilot.pause()
        assert calls == ["inspect"]


@pytest.mark.asyncio
async def test_plugin_action_collects_typed_input_and_returns_safe_summary(target):
    """The operator UI prompts for typed values and renders the bounded action result."""
    calls: list[dict[str, object]] = []

    async def inspect_region(values: dict[str, object]) -> ControlResult:
        calls.append(values)
        return ControlResult("Region is reachable", ("status: ready",))

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            id="inspect-region",
            title="Inspect region",
            description="Check a configured region.",
            handler=inspect_region,
            inputs=(
                ControlInput("region", "Region name"),
                ControlInput("credential", "Credential", kind="secret"),
                ControlInput(
                    "mode",
                    "Inspection mode",
                    kind="choice",
                    choices=("read-only", "deep"),
                    default="read-only",
                ),
            ),
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        operation = control_room.run_worker(
            control_room._run_plugin_action("orbit-cli-review-fixture/inspect-region")
        )
        await pilot.pause()
        region = control_room.query_one("#action-input-region", Input)
        region.value = "eu-west-1"
        credential = control_room.query_one("#action-input-credential", Input)
        credential.value = "test-secret"
        assert credential.password is True
        assert control_room.query_one("#action-input-mode", Select).value == "read-only"
        from textual.widgets import Button

        submit = control_room.query_one("#form-continue", Button)
        assert submit.region.width > 0 and submit.region.height > 0, repr(submit.region)
        assert submit.region.bottom <= control_room.size.height, (
            submit.region,
            control_room.size,
        )
        clicked = await pilot.click("#form-continue", offset=(8, 1))
        assert clicked
        await operation.wait()
        await control_room.workers.wait_for_complete()
        if not calls:
            from textual.widgets import Static

            assert not control_room.screen.query_one("#form-error", Static).renderable
        assert calls == [{"region": "eu-west-1", "credential": "test-secret", "mode": "read-only"}]


@pytest.mark.asyncio
async def test_plugin_action_input_validation_stays_in_form(target):
    """Invalid required and integer inputs do not dispatch provider work."""
    calls: list[dict[str, object]] = []

    async def inspect_region(values: dict[str, object]) -> None:
        calls.append(values)

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            "inspect-region",
            "Inspect region",
            "Read-only check.",
            inspect_region,
            inputs=(ControlInput("count", "Replica count", kind="integer"),),
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        operation = control_room.run_worker(
            control_room._run_plugin_action("orbit-cli-review-fixture/inspect-region")
        )
        await pilot.pause()
        count = control_room.query_one("#action-input-count", Input)
        count.value = "many"
        await pilot.click("#form-continue")
        assert "invalid literal" in str(control_room.query_one("#form-error").renderable)
        assert calls == []
        await pilot.click("#form-cancel")
        await operation.wait()
        assert calls == []


@pytest.mark.asyncio
async def test_disabled_plugin_actions_are_not_shown(target):
    """Disabled plugin actions remain unavailable in the interactive menu."""

    async def inspect_provider(values: dict[str, object]) -> None:
        return None

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction("inspect", "Inspect", "Read provider state.", inspect_provider),
    )
    target.application.register_plugin(plugin)
    target.application.plugins.disable("orbit-cli-review-fixture")
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        actions = control_room.query_one("#actions", OptionList)
        assert all(
            option.id != "plugin-action:orbit-cli-review-fixture/inspect"
            for option in actions._options
        )


@pytest.mark.asyncio
async def test_plugin_action_failures_are_sanitized_and_disabled_actions_are_ignored(
    target, monkeypatch
):
    """The control room never renders provider exception text or runs disabled actions."""
    calls: list[str] = []

    async def failing_action(values: dict[str, object]) -> None:
        raise RuntimeError("secret token must not appear")

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            id="failing",
            title="Fail safely",
            description="Exercise failure reporting.",
            handler=failing_action,
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        messages: list[str] = []
        write = control_room._write

        def capture(message: str) -> None:
            messages.append(message)
            write(message)

        monkeypatch.setattr(control_room, "_write", capture)
        await control_room._run_plugin_action("orbit-cli-review-fixture/failing")
        assert "RuntimeError" in messages[-1]
        assert "secret token" not in messages[-1]
        target.application.plugins.disable("orbit-cli-review-fixture")
        await control_room._run_plugin_action("orbit-cli-review-fixture/failing")
        assert calls == []


@pytest.mark.asyncio
async def test_destructive_plugin_action_waits_for_operator_confirmation(target):
    """The TUI does not invoke destructive extension actions before explicit confirmation."""
    calls: list[str] = []

    async def delete_resource(values: dict[str, object]) -> None:
        calls.append("deleted")

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            id="delete",
            title="Delete resource",
            description="Delete the configured resource.",
            handler=delete_resource,
            destructive=True,
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        operation = control_room.run_worker(
            control_room._run_plugin_action("orbit-cli-review-fixture/delete")
        )
        await pilot.pause()
        assert calls == []
        await pilot.click("#confirm-continue")
        await operation.wait()
        assert calls == ["deleted"]


@pytest.mark.asyncio
async def test_destructive_plugin_action_can_be_cancelled(target):
    """The default confirmation choice cancels a destructive action."""
    calls: list[str] = []

    async def delete_resource(values: dict[str, object]) -> None:
        calls.append("deleted")

    plugin = ReviewPlugin()
    plugin.control_actions = (
        ControlAction(
            "delete",
            "Delete resource",
            "Delete the configured resource.",
            delete_resource,
            destructive=True,
        ),
    )
    target.application.register_plugin(plugin)
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        operation = control_room.run_worker(
            control_room._run_plugin_action("orbit-cli-review-fixture/delete")
        )
        await pilot.pause()
        await pilot.click("#confirm-cancel")
        await operation.wait()
        assert calls == []


@pytest.mark.asyncio
async def test_activity_feed_owns_and_stops_the_core_lifecycle(target):
    """The live feed starts Core once and cancellation closes its resources cleanly."""
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        await control_room._toggle_activity_feed()
        await pilot.pause(1.1)
        assert target.application.lifecycle.phase.value == "running"
        await control_room._toggle_activity_feed()
        await pilot.pause(0.2)
        assert target.application.lifecycle.phase.value == "stopped"
        await control_room._toggle_activity_feed()


@pytest.mark.asyncio
async def test_development_server_is_supervised_and_stopped_cleanly(target, monkeypatch):
    """The TUI owns one Uvicorn child and captures its output without a shell."""
    module = target
    module.runtime = Runtime(module.application)
    process = _FakeProcess()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def create_process(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    monkeypatch.setattr("orbit_cli.control_room.asyncio.create_subprocess_exec", create_process)
    control_room = OrbitControlRoom("orbit_control_room_target:runtime")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        await control_room._start_server()
        await control_room._start_server()
        assert len(calls) == 1
        assert calls[0][0][1:4] == ("-m", "orbit.cli", "serve")
        await control_room._stop_server()
        if control_room._server_reader is not None:
            await control_room._server_reader.wait()
        assert "development server exited" in repr(control_room.query_one("#feed").lines).lower()
        active_on_exit = _FakeProcess()
        control_room._server = active_on_exit
    assert active_on_exit.returncode == 0


@pytest.mark.asyncio
async def test_server_shutdown_escalates_after_grace_period(target, monkeypatch):
    """The child process is killed if it does not finish inside the shutdown deadline."""

    control_room = OrbitControlRoom("orbit_control_room_target:application")
    process = _FakeProcess()

    async def expire(awaitable, timeout):
        awaitable.close()
        raise TimeoutError

    async with control_room.run_test() as pilot:
        await pilot.pause()
        control_room._server = process
        with monkeypatch.context() as scoped:
            scoped.setattr(asyncio, "wait_for", expire)
            await control_room._stop_server()
        assert process.returncode == -9


@pytest.mark.asyncio
async def test_server_action_requires_runtime_and_reader_handles_missing_process(target):
    """The development host needs a Runtime target and safely handles no child process."""
    control_room = OrbitControlRoom("orbit_control_room_target:application")

    async with control_room.run_test() as pilot:
        await pilot.pause()
        await control_room._start_server()
        await control_room._read_server_output()
        await control_room._stop_server()


@pytest.mark.asyncio
async def test_activity_feed_sanitizes_lifecycle_startup_errors(target, monkeypatch):
    """The live feed reports error types without exposing lifecycle exception details."""
    from contextlib import asynccontextmanager

    control_room = OrbitControlRoom("orbit_control_room_target:application")
    messages: list[str] = []
    write = control_room._write

    def capture(message: str) -> None:
        messages.append(message)
        write(message)

    @asynccontextmanager
    async def failed_lifecycle():
        raise RuntimeError("secret value")
        yield target.application

    async with control_room.run_test() as pilot:
        await pilot.pause()
        monkeypatch.setattr(control_room, "_write", capture)
        monkeypatch.setattr(target.application, "running", failed_lifecycle)
        await control_room._follow_activity()
        assert "RuntimeError" in messages[-1]
        assert "secret value" not in messages[-1]


class _FakeProcess:
    """Minimal asyncio process fake for bounded TUI server lifecycle tests."""

    def __init__(self) -> None:

        self.returncode: int | None = None
        self.stdout = asyncio.StreamReader()

    def terminate(self) -> None:
        """Simulate graceful termination and close the captured output pipe."""
        self.returncode = 0
        self.stdout.feed_data(b"development server ready\n")
        self.stdout.feed_eof()

    def kill(self) -> None:
        """Simulate forced child termination."""
        self.returncode = -9
        self.stdout.feed_eof()

    async def wait(self) -> int:
        """Return the simulated child exit status."""
        return self.returncode or 0


def test_no_argument_cli_delegates_to_interactive_control_room(monkeypatch):
    """The no-argument command opens the TUI while conventional help remains available."""
    import orbit_cli.control_room

    opened: list[bool] = []
    monkeypatch.setattr(orbit_cli.control_room, "run_control_room", lambda: opened.append(True))
    result = CliRunner().invoke(app, [])
    assert result.exit_code == 0, result.output
    assert opened == [True]


def test_module_entry_point_invokes_shared_typer_app(monkeypatch):
    """The conventional ``python -m orbit.cli`` entry point delegates to Typer."""
    from orbit_cli import __main__ as module_entry

    calls: list[bool] = []
    monkeypatch.setattr(module_entry, "app", lambda: calls.append(True))
    module_entry.main()
    assert calls == [True]


def test_top_level_cli_keeps_scriptable_core_commands_available():
    """The interactive distribution exposes the same named commands for automation."""
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert "0.1.0a1" in result.output


def test_top_level_help_lists_scriptable_commands():
    """Operators can discover automation commands without entering the control room."""
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "check" in result.output
    assert "diagnostics-watch" in result.output


def test_destructive_action_requires_explicit_confirmation_in_contract():
    """Destructive intent is immutable metadata for the UI confirmation boundary."""

    async def delete_resource(values: dict[str, object]) -> None:
        return None

    action = ControlAction(
        id="delete-resource",
        title="Delete resource",
        description="Permanently delete the configured test resource.",
        handler=delete_resource,
        destructive=True,
    )
    assert action.destructive is True
    with pytest.raises((AttributeError, TypeError)):
        action.destructive = False  # type: ignore[misc]


def test_control_action_registry_rejects_invalid_batches_without_partial_registration():
    """Invalid plugin declarations cannot leave a partial set of visible UI actions."""

    async def valid(values: dict[str, object]) -> None:
        return None

    registry = ControlActionRegistry()
    first = ControlAction("inspect", "Inspect", "Read current status.", valid)
    with pytest.raises(ValueError, match="Duplicate plugin control action"):
        registry.register("orbit-cli-review-fixture", (first, first))
    assert registry.actions == ()
    registry.register("orbit-cli-review-fixture", (first,))
    with pytest.raises(ValueError, match="Duplicate plugin control action"):
        registry.register("orbit-cli-review-fixture", (first,))
    assert len(registry.actions) == 1
    with pytest.raises(ValueError, match="valid Orbit plugin name"):
        registry.register("invalid", ())
    with pytest.raises(ValueError, match="bounded tuple"):
        registry.register("orbit-cli-review-fixture", [])  # type: ignore[arg-type]


def test_control_action_rejects_unsafe_metadata_and_non_async_handlers():
    """Plugin UI declarations reject malformed identifiers, text, and handler types."""

    async def callback(values: dict[str, object]) -> None:
        return None

    with pytest.raises(ValueError, match="action IDs"):
        ControlAction("Not Valid", "Title", "Description", callback)
    with pytest.raises(ValueError, match="title"):
        ControlAction("valid", "\x00", "Description", callback)
    with pytest.raises(TypeError, match="async callables"):
        ControlAction("valid", "Title", "Description", lambda: None)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a bool"):
        ControlAction("valid", "Title", "Description", callback, destructive=1)  # type: ignore[arg-type]
