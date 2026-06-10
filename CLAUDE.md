# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an early-stage Python bot project. The current runnable entry point is `main.py`, and the codebase is organized around a `Core/` package that is intended to hold the bot's major subsystems.

The repository is only partially wired today: many `Core/` modules currently contain docstrings/placeholders rather than implementations, and the active entry point does not yet integrate them.

## Development Commands

### Environment and dependencies

- Install dependencies with `uv sync`
- Run the app with `uv run python main.py`
- Alternative direct run: `python main.py`

### Tests

- There are currently no test files in the repository.
- The Visual Studio project is configured for `unittest` in `AIBot.pyproj`, so when tests are added the default discovery command should be `python -m unittest discover`.
- Run a single test module with `python -m unittest path.to.test_module`
- Run a single test case with `python -m unittest path.to.test_module.TestClass.test_method`

## Important Repository State

- `pyproject.toml` requires Python `>=3.12`.
- `.python-version` is `3.12`.
- `AIBot.pyproj` is still configured around Python 3.11 and `unittest`.
- There are two local environments present: `.venv/` and `env/`.
- `README.md` is currently empty.

When changing interpreter-related tooling, verify whether the project should standardize on Python 3.12 and whether the Visual Studio project file should be updated to match.

## Architecture

### Entry point

- `main.py` is the current startup script.
- Right now it only imports `modelcall` and prints a placeholder message.
- `AIBot.pyproj` also points its `StartupFile` at `main.py`.

### Core package layout

The intended application structure is split by responsibility under `Core/`:

- `Core/ModelCall/modelcall.py`: model API wrapper. It reads `APIKEY` and `URL` from environment variables and posts a chat payload with `requests`.
- `Core/agent/agent.py`: intended agent abstraction layer.
- `Core/task/task.py`: intended task execution/management layer.
- `Core/skill/skillmanager.py`: intended skill registry or skill orchestration layer.
- `Core/memory/memory.py`: intended memory subsystem for agent state.
- `Core/data/datamanager.py`: intended data persistence/management layer.
- `Core/soul/soul.py`: intended persona/state layer.
- `Core/mcp/localmcp.py`: intended local MCP tool aggregation, with comments indicating local tool state should be stored beside it in `localmcpdata.json`.
- `Core/mcp/onlinemcp.py`: intended online MCP tool aggregation, with comments indicating fetched tool state should be stored beside it in `onlinemcpdata.json`.

The architectural intent appears to be a layered bot system where `agent` coordinates behavior, `task` and `skill` handle execution capabilities, `memory` and `data` manage persistence/state, `soul` defines persona, `mcp` exposes tools, and `ModelCall` handles outbound model requests.

### Model integration details

`Core/ModelCall/modelcall.py` is the only module with concrete implementation logic at the moment:

- It imports `dotenv` but does not currently call `dotenv.load_dotenv()`, so environment variables must already be present in the process environment unless this is fixed.
- It expects `APIKEY` and `URL` variables.
- It sends a request payload with `model` set to `deepseek-v4-pro-guan`.
- The function `BaseModelCall(AIrole: str = "", text: str = "")` currently builds and sends the request but does not yet return parsed response data.

Any work that depends on model output should first verify whether this module should be completed, replaced, or adapted to the intended provider.

## Working Notes For Future Sessions

- Prefer reading `AIBot.pyproj` as well as `pyproject.toml` before changing run/test/tooling behavior; the repo currently has mixed `uv` and Visual Studio project metadata.
- Treat most files under `Core/` as design stubs unless you add the missing implementations yourself.
- Be careful with import casing on Windows vs other platforms: the directory is `Core/ModelCall/`, while `AIBot.pyproj` also references `Core\modelcall\...` in some entries. Standardize casing before introducing cross-platform assumptions.
