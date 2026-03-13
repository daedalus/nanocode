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


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Autonomous AI Agent with advanced tool use"
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default="config.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--provider", "-p",
        type=str,
        choices=["openai", "anthropic", "ollama", "lm-studio"],
        help="LLM provider to use",
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        help="Model to use",
    )
    parser.add_argument(
        "--no-planning",
        action="store_true",
        help="Disable planning phase",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--gui", "-g",
        choices=["ncurses", "cli"],
        default="cli",
        help="UI mode (default: cli)",
    )
    parser.add_argument(
        "--acp",
        action="store_true",
        help="Start ACP (Agent Client Protocol) server",
    )
    parser.add_argument(
        "--cwd",
        type=str,
        default=".",
        help="Working directory for ACP server",
    )
    return parser.parse_args()


async def run_cli(agent):
    """Run the CLI interface."""
    cli = InteractiveCLI(agent)
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


async def main():
    """Main entry point."""
    args = parse_args()
    
    if args.acp:
        os.chdir(args.cwd)
        config = Config(args.config)
        agent = AutonomousAgent(config)
        await run_acp(agent)
        return
    
    config = Config(args.config)
    
    if args.provider:
        config.set("llm.default_provider", args.provider)
    if args.model:
        config.set(f"llm.providers.{args.provider or config.default_provider}.model", args.model)
    
    agent = AutonomousAgent(config)
    
    if args.gui == "ncurses":
        success = run_ncurses(agent)
        if not success:
            print("Using CLI mode instead...")
            await run_cli(agent)
    else:
        await run_cli(agent)


if __name__ == "__main__":
    asyncio.run(main())
