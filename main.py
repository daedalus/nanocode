#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

import asyncio
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_smith.core import AutonomousAgent
from agent_smith.cli import InteractiveCLI
from agent_smith.config import Config
from agent_smith.server import run_server


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Autonomous AI Agent with advanced tool use")
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
        choices=["ncurses", "cli", "text"],
        default="cli",
        help="UI mode: cli (default), ncurses, text (modern terminal UI)",
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
    return parser.parse_args()


async def run_cli(agent, show_thinking: bool = True):
    """Run the CLI interface."""
    cli = InteractiveCLI(agent, show_thinking=show_thinking)
    await cli.run()


async def run_acp(agent):
    """Run the ACP server."""
    from agent_smith.acp import ACPServer

    print("Starting ACP server...")
    server = ACPServer(agent)
    await server.start()


def run_ncurses(agent):
    """Run the ncurses interface. Returns True if successful, False if fallback needed."""
    import curses
    from agent_smith.cli.ncurses import NcursesGUI

    async def handle_message(msg):
        try:
            response = await agent.process_input(msg)
        except Exception as e:
            response = f"Error: {str(e)}"
        return response

    gui = NcursesGUI(agent, handle_message)

    try:
        stdscr = curses.initscr()
        curses.endwin()

        stdscr = curses.initscr()
        gui.run(stdscr)
        return True
    except curses.error as e:
        print(f"\nNCurses not available: {e}")
        try:
            curses.endwin()
        except:
            pass
        return False


def run_text(agent):
    """Run the text-based terminal interface."""
    from agent_smith.cli.textgui import run_text as run_text_gui

    run_text_gui(agent)


async def main():
    """Main entry point."""
    args = parse_args()

    if args.serve:
        os.chdir(args.cwd)
        config = Config(args.config)

        auth_username = None
        auth_password = None
        if args.serve_auth:
            if ":" in args.serve_auth:
                auth_username, auth_password = args.serve_auth.split(":", 1)
            else:
                auth_username = args.serve_auth

        agent = AutonomousAgent(config)

        if args.mdns:
            try:
                from agent_smith.mdns import get_manager

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
        agent = AutonomousAgent(config)
        await run_acp(agent)
        return

    if args.admin:
        os.chdir(args.cwd)
        config = Config(args.config)
        from agent_smith.admin import start_admin_console

        runner = await start_admin_console(
            config=config,
            host=args.admin_host,
            port=args.admin_port,
        )
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            await runner.cleanup()
        return

    config = Config(args.config)

    if args.provider:
        config.set("llm.default_provider", args.provider)
    if args.model:
        config.set(f"llm.providers.{args.provider or config.default_provider}.model", args.model)

    agent = AutonomousAgent(config)

    show_thinking = getattr(args, "thinking", True)

    if args.gui == "ncurses":
        success = run_ncurses(agent)
        if not success:
            print("Using CLI mode instead...")
            await run_cli(agent, show_thinking=show_thinking)
    elif args.gui == "text":
        run_text(agent)
    else:
        await run_cli(agent, show_thinking=show_thinking)


if __name__ == "__main__":
    asyncio.run(main())
