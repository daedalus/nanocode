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
        default="0.0.0.0",
        help="HTTP server host (default: 0.0.0.0)",
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
        "--install-skills",
        type=str,
        metavar="SKILL",
        help="Install a skill by name (e.g., 'redteaming') or 'all' for all skills",
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


async def main():
    """Main entry point."""
    args = parse_args()

    if args.list_sessions:
        from nanocode.session_manager import get_session_manager

        mgr = get_session_manager()
        sessions = mgr.list()
        if not sessions:
            print("No sessions found")
            return
        print("Sessions:")
        for s in sessions:
            print(
                f"  {s.id}: {s.title} (updated: {s.updated_at.strftime('%Y-%m-%d %H:%M')})"
            )
        return

    gui_mode = getattr(args, "gui", "cli")

    if args.install_skills:
        from nanocode.skills import install_skills

        if args.install_skills == "all":
            install_skills()
        else:
            install_skills(args.install_skills)
        return

    if args.serve:
        os.chdir(args.cwd)
        config = Config(args.config)
        if args.no_proxy:
            config.set("proxy", None)
        elif args.proxy:
            config.set("proxy", args.proxy)
        if args.user_agent:
            config.set("user_agent", args.user_agent)

        auth_username = None
        if args.serve_auth:
            if ":" in args.serve_auth:
                auth_username, auth_password = args.serve_auth.split(":", 1)
            else:
                auth_username = args.serve_auth

        agent = AutonomousAgent(
            config,
            session_id=args.resume,
            verbose=args.verbose,
            yolo=args.yolo,
            drift_alert=args.drift_alert,
            drift_intervene=args.drift_intervene,
            auto_execute=args.auto_execute,
        )
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

        await run_server(
            host=args.serve_host,
            port=args.serve_port,
            agent=agent,
            auth_username=auth_username,
            auth_password=auth_password,
        )
        return

    if args.acp:
        os.chdir(args.cwd)
        config = Config(args.config)
        if args.no_proxy:
            config.set("proxy", None)
        elif args.proxy:
            config.set("proxy", args.proxy)
        if args.user_agent:
            config.set("user_agent", args.user_agent)
        agent = AutonomousAgent(
            config,
            session_id=args.resume,
            yolo=args.yolo,
            drift_alert=args.drift_alert,
            drift_intervene=args.drift_intervene,
            auto_execute=args.auto_execute,
        )
        await agent.init_async()
        await run_acp(agent)
        return

    if args.admin:
        os.chdir(args.cwd)
        config = Config(args.config)
        if args.no_proxy:
            config.set("proxy", None)
        elif args.proxy:
            config.set("proxy", args.proxy)
        if args.user_agent:
            config.set("user_agent", args.user_agent)
        from nanocode.admin import start_admin_console

        runner = await start_admin_console(
            config=config,
            host=args.admin_host,
            port=args.admin_port,
        )
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            session_id = (
                getattr(agent, "_session_id", "unknown") if agent else "unknown"
            )
            print()
            c = Console()
            c.print(
                "[cyan]░██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗  █████╗ ██████╗ ██████╗ [/cyan]"
            )
            c.print(
                "[cyan]██╔════╝ ██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗[/cyan]"
            )
            c.print(
                "[cyan]██║  ███╗█████╗     ██║   ██████╔╝██║   ██║██████╔╝███████║██████╔╝███████║[/cyan]"
            )
            c.print(
                "[cyan]██║   ██║██╔══╝     ██║   ██╔══██╗██║   ██║██╔══██╗██╔══██║██╔══██╗██╔══██║[/cyan]"
            )
            c.print(
                "[cyan]╚██████╔╝███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██║  ██║██║  ██║██║  ██║[/cyan]"
            )
            c.print(
                "[cyan] ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝[/cyan]"
            )
            print()
            print(f"Session: {session_id}")
        finally:
            await runner.cleanup()
        return

    config = Config(args.config)

    print(f"nanocode v{__version__}")

    if args.no_proxy:
        config.set("proxy", None)
    elif args.proxy:
        config.set("proxy", args.proxy)
    if args.user_agent:
        config.set("user_agent", args.user_agent)
    if args.cache:
        config.set("cache.enabled", True)
    if args.use_context_strategy:
        config.set("context.strategy", args.use_context_strategy)

    if args.provider:
        config.set("llm.default_connector", args.provider)
    if args.model:
        config.set(
            f"llm.connectors.{args.provider or config.default_connector}.model",
            args.model,
        )

    agent = AutonomousAgent(
        config,
        session_id=args.resume,
        verbose=args.verbose,
        yolo=args.yolo,
        drift_alert=args.drift_alert,
        drift_intervene=args.drift_intervene,
        auto_execute=args.auto_execute,
    )
    await agent.init_async()
    atexit.register(lambda: _save_session_on_exit(agent))

    show_thinking = getattr(
        args, "thinking", False
    )  # Default: disabled (use --thinking to enable)
    show_messages = getattr(args, "show_messages", False)
    gui_show_thinking = True if gui_mode == "textual" else show_thinking

    import logging

    log_file = getattr(args, "log_file", None)
    debug_arg = getattr(args, "debug", None)

    def _configure_debug_logging(concerns: list[str], gui_mode: str = None):
        """Configure logging for specified concerns."""
        valid_concerns = {"agent", "tools", "cache", "context", "llm", "tui", "all"}
        if "all" in concerns:
            level = logging.DEBUG
        else:
            level = logging.DEBUG

        handlers = [
            logging.FileHandler(log_file)
            if log_file
            else logging.FileHandler("/tmp/nanocode.log")
        ]

        # Only add StreamHandler when --debug is used AND NOT in TUI mode
        # StreamHandler writes to stderr which causes TUI flicker
        if debug_arg and gui_mode != "textual":
            handlers.append(logging.StreamHandler())

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

        if "all" not in concerns:
            for name in logging.Logger.manager.loggerDict:
                logger = logging.getLogger(name)
                if not any(c in name for c in concerns):
                    logger.setLevel(logging.WARNING)

    # Configure logging based on --debug and --log-file
    should_debug = debug_arg or log_file or gui_mode == "textual"
    if debug_arg:
        concerns = [c.strip().lower() for c in debug_arg.split(",")]
        invalid = set(concerns) - {
            "agent",
            "tools",
            "cache",
            "context",
            "llm",
            "tui",
            "all",
        }
        if invalid:
            print(
                f"Warning: Unknown debug concerns: {invalid}. Valid options: agent, tools, cache, context, llm, tui, all"
            )
            concerns = [
                c
                for c in concerns
                if c in {"agent", "tools", "cache", "context", "llm", "tui", "all"}
            ]
            if not concerns:
                concerns = ["all"]
        _configure_debug_logging(concerns, gui_mode)
    elif log_file or gui_mode == "textual":
        # In TUI mode, only use file handler to avoid stderr spam
        handlers = [
            logging.FileHandler(log_file)
            if log_file
            else logging.FileHandler("/tmp/nanocode.log")
        ]
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

    # Non-interactive mode: read from stdin or file, process, and exit
    non_interactive = getattr(args, "non_interactive", False)
    input_file = getattr(args, "input_file", None)
    use_stdin = getattr(args, "stdin", False)
    prompt_arg = getattr(args, "prompt", None)

    # Single prompt mode or full batch non-interactive mode
    if prompt_arg or non_interactive or input_file or use_stdin:
        import sys

        # Determine input source
        if prompt_arg:
            content = str(prompt_arg)
        elif use_stdin:
            content = sys.stdin.read()
            if not content.strip():
                print("No input from stdin", file=sys.stderr)
                return
        elif input_file:
            input_path = Path(input_file)
            if not input_path.exists():
                print(f"Input file not found: {input_file}", file=sys.stderr)
                return
            content = input_path.read_text()
        else:
            print("Non-interactive mode requires --input-file, --stdin, or --prompt", file=sys.stderr)
            return

        # Parse prompts from content
        sep = getattr(args, "separator", None) or "\n"
        if sep == "blank":
            prompts = [p.strip() for p in content.split("\n\n") if p.strip()]
        elif sep == "---":
            prompts = [p.strip() for p in content.split("\n---\n") if p.strip()]
        else:
            prompts = content.split(sep)

        # Auto-allow all permissions in non-interactive mode
        auto_ask_allow = getattr(args, "auto_ask_allow", False)
        auto_ask_deny = getattr(args, "auto_ask_deny", False)

        if auto_ask_allow:
            async def auto_ask_permission(request):
                return PermissionReply(
                    request_id=request.id,
                    reply=PermissionReplyType.ALLOW,
                )
        elif auto_ask_deny:
            async def auto_ask_permission(request):
                return PermissionReply(
                    request_id=request.id,
                    reply=PermissionReplyType.REJECT,
                    message="Permission denied (auto-ask-deny mode)",
                )
        else:
            async def auto_ask_permission(request):
                return PermissionReply(
                    request_id=request.id,
                    reply=PermissionReplyType.ALLOW,
                )

        agent.permission_handler.set_callback(auto_ask_permission)

        results = []
        output_file = getattr(args, "output", None)

        for idx, prompt in enumerate(prompts):
            if not prompt.strip():
                continue

            print(f"\n[{idx + 1}/{len(prompts)}] Processing...")
            import asyncio

            print(f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

            try:
                # Add timeout to prevent hanging
                result = await asyncio.wait_for(
                    agent.process_input(
                        prompt, show_thinking=show_thinking, show_messages=show_messages
                    ),
                    timeout=120.0  # 2 minute max per prompt
                )
                print(f"[MAIN] process_input returned: {type(result)}, len={len(result) if result else 0}")
                if result:
                    results.append(result)
                    print(f"Response: {result[:200]}{'...' if len(result) > 200 else ''}")
                else:
                    print("Warning: agent returned empty result")
            except asyncio.TimeoutError:
                # Try to get partial result from agent state
                partial = getattr(agent, "state", {}).last_summary if hasattr(agent, "state") else None
                result = f"Timeout - partial results may be available. Last summary: {partial}"
                results.append(result)
                print(f"[MAIN] Timeout - partial: {result}")
            except Exception as err:
                import traceback as tb

                tb.print_exc()
                result = f"Error: {str(err)}"
                results.append(result)

        final_result = "\n\n---\n\n".join(results)

        if output_file:
            Path(output_file).write_text(final_result)
            print(f"Result written to: {output_file}")
        else:
            print("\n" + "=" * 60)
            print("AGENT RESPONSE(S):")
            print("=" * 60)
            print(final_result)

        if hasattr(agent, "save_session"):
            agent.save_session()
        return

    if gui_mode == "cli":
        await run_cli(
            agent,
            show_thinking=show_thinking,
            show_messages=show_messages,
            enable_spinner=not getattr(args, "no_spinner", False),
        )
    else:
        await run_tui(
            agent, show_thinking=gui_show_thinking, show_messages=show_messages
        )


def _format_markdown(text: str) -> str:
    """Format markdown bold (**text**) as bold + magenta using Rich markup."""
    import re

    def replace_bold(match):
        return f"[magenta bold]{match.group(1)}[/magenta bold]"

    return re.sub(r"\*\*(.+?)\*\*", replace_bold, text)


if __name__ == "__main__":
    asyncio.run(main())
