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
"""Launch the interactive control room and retain Core's conventional commands."""

from __future__ import annotations

import typer
from orbit.cli.app import app as core_app

app = typer.Typer(
    no_args_is_help=False,
    invoke_without_command=True,
    help="Open the interactive Orbit control room or use scriptable commands.",
)
# Core remains the owner of scriptable operations. Copy its command registrations to keep
# ``orbit check`` and similar commands available without making Core depend on Textual.
app.registered_commands.extend(core_app.registered_commands)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Open the interactive control room when the operator selects no command."""
    if ctx.invoked_subcommand is None:
        from orbit_cli.control_room import run_control_room

        run_control_room()
