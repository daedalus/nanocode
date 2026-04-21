#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

import asyncio
import argparse
import atexit
import os

from nanocode.core import AutonomousAgent
from nanocode.cli import InteractiveCLI
from nanocode.config import Config
from nanocode.server import run_server


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
        "--config",
        "-c",
        type=str,
        default="config.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--provider",
        "-p",
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
        "--prompt",
        type=str,
        help="Run a single prompt and exit (non-interactive mode)",
    )
    parser.add_argument(
        "--debug-logging",
        action="store_true",
        help="Enable debug logging",
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
        "--resume",
        "-r",
        type=str,
        default=None,
        help="Resume an existing session by ID",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List all sessions",
    )
    return parser.parse_args()


async def run_cli(agent, show_thinking: bool = False, show_messages: bool = False, enable_spinner: bool = True):
    """Run the CLI interface."""
    from nanocode.agents.permission import (
        PermissionCallback,
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
                return PermissionReply(request_id=request.id, reply=PermissionReplyType.ONCE)
            elif response == "always":
                return PermissionReply(request_id=request.id, reply=PermissionReplyType.ALWAYS)
            else:
                return PermissionReply(request_id=request.id, reply=PermissionReplyType.REJECT, message="Permission denied by user")
        except (KeyboardInterrupt, EOFError):
            return PermissionReply(request_id=request.id, reply=PermissionReplyType.REJECT, message="Permission denied by user")

    agent.permission_handler.set_callback(permission_callback)

    cli = InteractiveCLI(
        agent, show_thinking=show_thinking, show_messages=show_messages,
        enable_spinner=enable_spinner
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
            print(f"  {s.id}: {s.title} (updated: {s.updated_at.strftime('%Y-%m-%d %H:%M')})")
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

        agent = AutonomousAgent(config, session_id=args.resume, verbose=args.verbose)

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
        agent = AutonomousAgent(config, session_id=args.resume)
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
            session_id = getattr(agent, '_session_id', 'unknown') if agent else 'unknown'
            print()
            print("\033[96m" + "░██████╗ ███████╗████████╗██████╗  ██████╗ ██████╗  █████╗ ██████╗ ██████╗ " + "\033[0m")
            print("\033[96m" + "██╔════╝ ██╔════╝╚══██╔══╝██╔══██╗██╔═══██╗██╔══██╗██╔══██╗██╔══██╗██╔══██╗" + "\033[0m")
            print("\033[96m" + "██║  ███╗█████╗     ██║   ██████╔╝██║   ██║██████╔╝███████║██████╔╝███████║" + "\033[0m")
            print("\033[96m" + "██║   ██║██╔══╝     ██║   ██╔══██╗██║   ██║██╔══██╗██╔══██║██╔══██╗██╔══██║" + "\033[0m")
            print("\033[96m" + "╚██████╔╝███████╗   ██║   ██║  ██║╚██████╔╝██████╔╝██║  ██║██║  ██║██║  ██║" + "\033[0m")
            print("\033[96m" + " ╚═════╝ ╚══════╝   ╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝" + "\033[0m")
            print()
            print(f"Session: {session_id}")
        finally:
            await runner.cleanup()
        return

    config = Config(args.config)

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
        config.set("llm.default_provider", args.provider)
    if args.model:
        config.set(
            f"llm.providers.{args.provider or config.default_provider}.model",
            args.model,
        )

    agent = AutonomousAgent(config, session_id=args.resume, verbose=args.verbose)
    atexit.register(lambda: _save_session_on_exit(agent))

    show_thinking = getattr(args, "thinking", False)  # Default: disabled (use --thinking to enable)
    show_messages = getattr(args, "show_messages", False)
    gui_show_thinking = True if gui_mode == "textual" else show_thinking

    import logging
    
    log_file = getattr(args, "log_file", None)
    
    # Always configure file logging (to capture debug output for TUI)
    # Only add StreamHandler when --debug-logging is explicitly passed
    if log_file or getattr(args, "debug_logging", False) or gui_mode == "textual":
        handlers = [logging.FileHandler(log_file) if log_file else logging.FileHandler("/tmp/nanocode.log")]
        
        # Only add StreamHandler if --debug-logging is explicitly passed
        if getattr(args, "debug_logging", False):
            handlers.append(logging.StreamHandler())
        
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
        )

    if getattr(args, "prompt", None):
        import traceback
        try:
            result = await agent.process_input(
                args.prompt, show_thinking=show_thinking, show_messages=show_messages
            )
        except Exception as e:
            traceback.print_exc()
            result = f"Error: {str(e)}"

        print("\n" + "=" * 60)
        print("AGENT RESPONSE:")
        print("=" * 60)
        if isinstance(result, str) and result.startswith("Error:"):
            print(result)
            print("\nFull traceback above.")
        else:
            formatted = _format_markdown(result)
            print(formatted)
        return

    if gui_mode == "cli":
        await run_cli(
            agent,
            show_thinking=show_thinking,
            show_messages=show_messages,
            enable_spinner=not getattr(args, "no_spinner", False)
        )
    else:
        await run_tui(agent, show_thinking=gui_show_thinking, show_messages=show_messages)


def _format_markdown(text: str) -> str:
    """Format markdown bold (**text**) as bold + magenta."""
    import re
    MAGENTA_BOLD = "\033[38;5;95;1m"
    RESET = "\033[0m"

    def replace_bold(match):
        return f"{MAGENTA_BOLD}{match.group(1)}{RESET}"

    return re.sub(r'\*\*(.+?)\*\*', replace_bold, text)


if __name__ == "__main__":
    asyncio.run(main())
