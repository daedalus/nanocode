#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

import argparse
import asyncio
import atexit
import os
from pathlib import Path

from rich.console import Console

from nanocode.cli import InteractiveCLI
from nanocode.config import Config
from nanocode.core import AutonomousAgent
from nanocode import __version__
from nanocode.server import run_server
from nanocode.agents.permission import (
    PermissionHandler,
    PermissionReply,
    PermissionReplyType,
)


def _save_session_on_exit(agent: AutonomousAgent):
    """Save session on program exit."""
    if agent:
        agent.save_session()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous AI Agent with advanced tool use"
    )
    parser.add_argument(
        "-p", "--prompt",
        type=str,
        default=None,
        help="Prompt to send to the agent",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=None,
        help="Path to config file (default: ~/.config/nanocode/config.yaml)",
    )
    parser.add_argument(
        "--resume",
        "-r",
        type=str,
        default=None,
        help="Resume an existing session by ID",
    )
    parser.add_argument(
        "--provider",
        "-P",
        type=str,
        choices=["openai", "anthropic", "ollama", "lm-studio"],
        help="LLM provider to use",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        help="Model to use",
    )
    parser.add_argument(
        "--no-planning",
        action="store_true",
        help="Disable planning phase",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--thinking",
        "-t",
        action="store_true",
        help="Show thinking/reasoning blocks",
    )
    parser.add_argument(
        "--gui",
        "-g",
        choices=["textual", "cli"],
        default="textual",
        help="UI mode (default: textual)",
    )
    parser.add_argument(
        "--no-spinner",
        action="store_true",
        help="Disable spinner animation in CLI mode",
    )
    parser.add_argument(
        "--acp",
        action="store_true",
        help="Start ACP (Agent Client Protocol) server",
    )
    parser.add_argument(
        "--yolo",
        "-y",
        action="store_true",
        help="YOLO mode: auto-approve all tool permissions without asking",
    )
    parser.add_argument(
        "--drift-alert",
        action="store_true",
        help="Drift watchdog: alert on goal drift (no intervention)",
    )
    parser.add_argument(
        "--drift-intervene",
        action="store_true",
        help="Drift watchdog: intervene and refocus on goal drift",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start HTTP server for remote operation",
    )
    parser.add_argument(
        "--serve-host",
        type=str,
        default="127.0.0.1",  # localhost only by default for security
        help="HTTP server host (default: 127.0.0.1, use 0.0.0.0 for all interfaces)",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=8080,
        help="HTTP server port (default: 8080)",
    )
    parser.add_argument(
        "--serve-auth",
        type=str,
        help="HTTP server auth (format: username:password)",
    )
    parser.add_argument(
        "--mdns",
        action="store_true",
        help="Publish service via mDNS",
    )
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Start admin console",
    )
    parser.add_argument(
        "--admin-host",
        type=str,
        default="127.0.0.1",
        help="Admin console host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--admin-port",
        type=int,
        default=7890,
        help="Admin console port (default: 7890)",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        default=".",
        help="Working directory for ACP/server",
    )
    parser.add_argument(
        "--working-directory",
        type=str,
        default=None,
        help="Working directory for agent operations (defaults to current directory)",
    )

    parser.add_argument(
        "--proxy",
        type=str,
        help="Proxy URL for HTTP requests (e.g., http://localhost:8080)",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable proxy for HTTP requests (override environment settings)",
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        help="Custom User-Agent for HTTP requests",
    )
    parser.add_argument(
        "--show-messages",
        action="store_true",
        help="Show messages exchanged with the LLM",
    )
    parser.add_argument(
        "--debug",
        "-d",
        type=str,
        default=None,
        help="Enable debug logging: agent, tools, cache, context, llm, tui, all (comma-separated)",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Log to file (default: /tmp/nanocode.log)",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Enable prompt/completion caching",
    )
    parser.add_argument(
        "--use-context-strategy",
        type=str,
        choices=["sliding_window", "summary", "importance", "compaction", "topic_id"],
        default=None,
        help="Context compaction strategy",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all sessions",
    )
    parser.add_argument(
        "--auto-execute",
        "-x",
        action="store_true",
        help="Enable auto-execution of commands found in file contents (potentially dangerous)",
    )
    parser.add_argument(
        "--non-interactive",
        "-n",
        action="store_true",
        help="Non-interactive mode: process input and exit (auto-allow permissions)",
    )
    parser.add_argument(
        "--auto-ask-allow",
        action="store_true",
        help="When permission is ASK, auto-allow (implies --non-interactive)",
    )
    parser.add_argument(
        "--auto-ask-deny",
        action="store_true",
        help="When permission is ASK, auto-deny (implies --non-interactive)",
    )
    parser.add_argument(
        "--input-file",
        "-i",
        type=str,
        default=None,
        help="Read prompts from file (one per line or blank-line separated)",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read prompts from stdin",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Write result to file instead of stdout",
    )
    parser.add_argument(
        "--separator",
        type=str,
        default="\n",
        help="Input separator: blank (default), '---' or custom string",
    )
    parser.add_argument(
        "--get-system-prompt",
        action="store_true",
        help="Print the current formatted system prompt and exit",
    )
    return parser.parse_args()


async def run_cli(
    agent,
    show_thinking: bool = True,
    show_messages: bool = False,
    enable_spinner: bool = True,
):
    """Run the CLI interface."""
    from nanocode.agents.permission import (
        PermissionReply,
        PermissionReplyType,
        PermissionRequest,
    )

    async def permission_callback(request: PermissionRequest) -> PermissionReply:
        """Callback to prompt user for permission in CLI."""
        from nanocode.cli import ConsoleUI

        ui = ConsoleUI()
        print(f"\n{ui.color('yellow', '┌─[PERMISSION REQUEST]')}")
        print(f"  {ui.color('cyan', 'Agent:')} {request.agent_name}")
        print(f"  {ui.color('cyan', 'Tool:')} {request.tool_name}")
        if request.arguments:
            print(f"  {ui.color('cyan', 'Arguments:')}")
            for k, v in request.arguments.items():
                v_str = str(v)
                print(f"    {k}: {v_str}")
        print(f"  {ui.color('magenta', '➜')} Allow? (y/n/a=always): ", end="")

        try:
            response = input().strip().lower()
            if response in ("y", "yes"):
                return PermissionReply(
                    request_id=request.id, reply=PermissionReplyType.ONCE
                )
            elif response == "always":
                return PermissionReply(
                    request_id=request.id, reply=PermissionReplyType.ALWAYS
                )
            else:
                return PermissionReply(
                    request_id=request.id,
                    reply=PermissionReplyType.REJECT,
                    message="Permission denied by user",
                )
        except (KeyboardInterrupt, EOFError):
            return PermissionReply(
                request_id=request.id,
                reply=PermissionReplyType.REJECT,
                message="Permission denied by user",
            )

    agent.permission_handler.set_callback(permission_callback)

    cli = InteractiveCLI(
        agent,
        show_thinking=show_thinking,
        show_messages=show_messages,
        enable_spinner=enable_spinner,
    )
    await cli.run()


async def run_tui(agent, show_thinking: bool = True, show_messages: bool = False):
    """Run the Textual TUI interface."""
    from nanocode.tui import run_tui as run_textual_tui

    await run_textual_tui(agent=agent, show_thinking=show_thinking)


async def run_acp(agent):
    """Run the ACP server."""
    from nanocode.acp import ACPServer

    print("Starting ACP server...")
    server = ACPServer(agent)
    await server.start()


async def _list_sessions():
    """List all sessions and exit."""
    from nanocode.session_manager import get_session_manager
    mgr = get_session_manager()
    sessions = mgr.list()
    if not sessions:
        print("No sessions found")
        return
    print("Sessions:")
    for s in sessions:
        print(f"  {s.id}: {s.title} (updated: {s.updated_at.strftime('%Y-%m-%d %H:%M')})")


async def _print_system_prompt(args):
    """Build and print the system prompt, then exit."""
    config = Config(args.config) if args.config else Config()
    agent = AutonomousAgent(config, verbose=getattr(args, 'verbose', False))
    print(agent._build_system_prompt())


def _apply_config_overrides(args, config):
    """Apply CLI argument overrides to config."""
    if args.no_proxy:
        config.set("proxy", None)
    elif args.proxy:
        config.set("proxy", args.proxy)
    if args.user_agent:
        config.set("user_agent", args.user_agent)
    if getattr(args, "cache", False):
        config.set("cache.enabled", True)
    if getattr(args, "use_context_strategy", None):
        config.set("context.strategy", args.use_context_strategy)
    if args.provider:
        config.set("llm.default_connector", args.provider)
    if args.model:
        config.set(f"llm.connectors.{args.provider or config.default_connector}.model", args.model)


def _create_agent(args, config):
    """Create an AutonomousAgent from parsed args and config."""
    return AutonomousAgent(
        config,
        session_id=args.resume,
        verbose=args.verbose,
        yolo=args.yolo,
        drift_alert=args.drift_alert,
        drift_intervene=args.drift_intervene,
        auto_execute=args.auto_execute,
    )


async def _run_serve_mode(args):
    """Start HTTP server mode."""
    os.chdir(args.cwd)
    config = Config(args.config)
    _apply_config_overrides(args, config)

    auth_username, auth_password = None, None
    if args.serve_auth:
        if ":" in args.serve_auth:
            auth_username, auth_password = args.serve_auth.split(":", 1)
        else:
            auth_username = args.serve_auth

    agent = _create_agent(args, config)
    await agent.init_async()

    if args.mdns:
        try:
            from nanocode.mdns import get_manager
            mdns = get_manager()
            await mdns.start()
            mdns.publish(args.serve_port)
            print(f"Published via mDNS on port {args.serve_port}")
        except ImportError:
            print("mDNS not available. Install: pip install zeroconf")

    await run_server(host=args.serve_host, port=args.serve_port, agent=agent,
                     auth_username=auth_username, auth_password=auth_password)


async def _run_acp_mode(args):
    """Start ACP server mode."""
    os.chdir(args.cwd)
    config = Config(args.config)
    _apply_config_overrides(args, config)
    agent = _create_agent(args, config)
    await agent.init_async()
    await run_acp(agent)


async def _run_admin_mode(args):
    """Start admin console mode."""
    os.chdir(args.cwd)
    config = Config(args.config)
    _apply_config_overrides(args, config)
    from nanocode.admin import start_admin_console
    runner = await start_admin_console(config=config, host=args.admin_host, port=args.admin_port)
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()


def _get_log_file_path(args):
    """Determine log file path from args or default."""
    if args.log_file:
        return args.log_file
    return os.path.join(
        os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
        "nanocode", "nanocode.log"
    )


def _configure_file_logging(log_file: str, gui_mode: str = None, debug_arg: str = None):
    """Set up logging with file handler. Optionally add stream handler."""
    handlers = [logging.FileHandler(log_file)]
    if debug_arg and gui_mode != "textual":
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=handlers,
    )


def _configure_filtered_logging(concerns: list[str], log_file: str, gui_mode: str = None, debug_arg: str = None):
    """Configure logging filtering by concern names."""
    _configure_file_logging(log_file, gui_mode, debug_arg)
    if "all" not in concerns:
        for name in logging.Logger.manager.loggerDict:
            logger = logging.getLogger(name)
            if not any(c in name for c in concerns):
                logger.setLevel(logging.WARNING)


def _setup_logging(args, gui_mode: str):
    """Configure logging based on --debug, --log-file, and UI mode."""
    import logging
    log_file = _get_log_file_path(args)
    debug_arg = args.debug
    if debug_arg:
        concerns = [c.strip().lower() for c in debug_arg.split(",")]
        valid = {"agent", "tools", "cache", "context", "llm", "tui", "all"}
        invalid = set(concerns) - valid
        if invalid:
            print(f"Warning: Unknown debug concerns: {invalid}. Valid options: agent, tools, cache, context, llm, tui, all")
            concerns = [c for c in concerns if c in valid] or ["all"]
        _configure_filtered_logging(concerns, log_file, gui_mode, debug_arg)
    elif debug_arg or log_file or gui_mode == "textual":
        _configure_file_logging(log_file, gui_mode)


async def _read_input_source(args) -> str | None:
    """Read content from the appropriate input source. Returns None if no source."""
    import sys
    if args.prompt:
        return str(args.prompt)
    if args.stdin:
        content = sys.stdin.read()
        if not content.strip():
            print("No input from stdin", file=sys.stderr)
        return content or None
    if args.input_file:
        input_path = Path(args.input_file)
        if not input_path.exists():
            print(f"Input file not found: {args.input_file}", file=sys.stderr)
            return None
        return input_path.read_text()
    return None


def _parse_prompts(content: str, separator: str) -> list[str]:
    """Split content into prompts based on separator."""
    if separator == "blank":
        return [p.strip() for p in content.split("\n\n") if p.strip()]
    elif separator == "---":
        return [p.strip() for p in content.split("\n---\n") if p.strip()]
    return content.split(separator)


def _make_permission_callback(auto_ask_allow: bool, auto_ask_deny: bool):
    """Create permission callback for non-interactive mode."""
    if auto_ask_deny:
        async def callback(request):
            return PermissionReply(
                request_id=request.id, reply=PermissionReplyType.REJECT,
                message="Permission denied (auto-ask-deny mode)",
            )
    else:
        async def callback(request):
            return PermissionReply(
                request_id=request.id, reply=PermissionReplyType.ALLOW,
            )
    return callback


async def _process_batch_prompts(args, agent, prompts: list[str], show_thinking: bool, show_messages: bool):
    """Process a batch of prompts and write output."""
    results = []
    output_file = args.output
    for idx, prompt in enumerate(prompts):
        if not prompt.strip():
            continue
        print(f"\n[{idx + 1}/{len(prompts)}] Processing...")
        print(f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
        try:
            result = await asyncio.wait_for(
                agent.process_input(prompt, show_thinking=show_thinking, show_messages=show_messages),
                timeout=120.0,
            )
            if result:
                results.append(result)
            else:
                print("Warning: agent returned empty result")
        except asyncio.TimeoutError:
            partial = getattr(agent, "state", {}).last_summary if hasattr(agent, "state") else None
            results.append(f"Timeout - partial results may be available. Last summary: {partial}")
        except Exception as err:
            import traceback as tb
            tb.print_exc()
            results.append(f"Error: {str(err)}")

    final_result = "\n\n---\n\n".join(results)
    if output_file:
        Path(output_file).write_text(final_result)
        print(f"Result written to: {output_file}")
    else:
        print("\n" + "=" * 60)
        print("AGENT RESPONSE(S):")
        print("=" * 60)
        print(final_result)


async def _handle_early_exit(args) -> bool:
    """Handle early-exit modes. Returns True if handled."""
    if args.list_sessions:
        await _list_sessions()
        return True
    if args.get_system_prompt:
        await _print_system_prompt(args)
        return True
    if args.serve:
        await _run_serve_mode(args)
        return True
    if args.acp:
        await _run_acp_mode(args)
        return True
    if args.admin:
        await _run_admin_mode(args)
        return True
    return False

async def _run_non_interactive(args, agent, show_thinking, show_messages):
    """Run in non-interactive (batch) mode."""
    content = await _read_input_source(args)
    if content is None:
        return
    sep = getattr(args, "separator", None) or "\n"
    prompts = _parse_prompts(content, sep)
    agent.permission_handler.set_callback(_make_permission_callback(getattr(args, "auto_ask_allow", False), getattr(args, "auto_ask_deny", False)))
    await _process_batch_prompts(args, agent, prompts, show_thinking, show_messages)
    if hasattr(agent, "save_session"):
        agent.save_session()

async def _run_interactive(args, agent, show_thinking, gui_mode, gui_show_thinking, show_messages):
    if gui_mode == "cli":
        await run_cli(agent, show_thinking=show_thinking, show_messages=show_messages, enable_spinner=not getattr(args, "no_spinner", False))
    else:
        await run_tui(agent, show_thinking=gui_show_thinking, show_messages=show_messages)

async def main():
    """Main entry point."""
    args = parse_args()
    if await _handle_early_exit(args):
        return

    gui_mode = getattr(args, "gui", "cli")
    if args.working_directory:
        os.chdir(args.working_directory)

    config = Config(args.config)
    print(f"nanocode v{__version__}")
    _apply_config_overrides(args, config)
    agent = _create_agent(args, config)
    await agent.init_async()
    atexit.register(lambda: _save_session_on_exit(agent))

    show_thinking = getattr(args, "thinking", False)
    show_messages = getattr(args, "show_messages", False)
    gui_show_thinking = True if gui_mode == "textual" else show_thinking
    _setup_logging(args, gui_mode)

    non_interactive = getattr(args, "non_interactive", False)
    if args.prompt or non_interactive or args.input_file or args.stdin:
        await _run_non_interactive(args, agent, show_thinking, show_messages)
        return

    await _run_interactive(args, agent, show_thinking, gui_mode, gui_show_thinking, show_messages)


def _format_markdown(text: str) -> str:
    """Format markdown bold (**text**) as bold + magenta using Rich markup."""
    import re

    def replace_bold(match):
        return f"[magenta bold]{match.group(1)}[/magenta bold]"

    return re.sub(r"\*\*(.+?)\*\*", replace_bold, text)


if __name__ == "__main__":
    asyncio.run(main())
