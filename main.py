#!/usr/bin/env python3
"""Entry point for the autonomous agent."""

import asyncio
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.core import AutonomousAgent
from agent.cli import InteractiveCLI
from agent.config import Config


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
    return parser.parse_args()


async def run_cli(agent):
    """Run the CLI interface."""
    cli = InteractiveCLI(agent)
    await cli.run()


def run_ncurses(agent):
    """Run the ncurses interface. Returns True if successful, False if fallback needed."""
    import curses
    from agent.cli.ncurses import NcursesGUI
    
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
