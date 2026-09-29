import argparse
import asyncio
import sys
from rich.console import Console

# Import the engine you just built
from engine import TorrentEngine

console = Console()

class Program:
    def __init__(self):
        self.args = self._parse_args()

    def _parse_args(self):
        """Sets up and parses command line arguments."""
        parser = argparse.ArgumentParser(description="Python BitTorrent CLI Client")
        
        parser.add_argument(
            "torrent_file", 
            help="Path to the .torrent file you want to download"
        )
        parser.add_argument(
            "-d", "--download-dir", 
            default=".", 
            help="Directory to save downloaded files (default: current directory)"
        )
        
        return parser.parse_args()

    def run(self):
        """Initializes the engine and starts the async event loop."""
        console.print(f"[bold cyan][*] Initializing client for: {self.args.torrent_file}[/bold cyan]\n")
        
        # Initialize the main orchestrator
        engine = TorrentEngine(self.args.torrent_file, self.args.download_dir)
        
        try:
            # Start the asynchronous event loop
            asyncio.run(engine.start())
        except KeyboardInterrupt:
            # Catches CTRL+C so the program doesn't throw a massive error trace
            console.print("\n[bold yellow][*] Shutting down client gracefully[/bold yellow]")
            sys.exit(0)

if __name__ == "__main__":
    app = Program()
    app.run()