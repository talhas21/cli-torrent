import asyncio
from rich.console import Console
from rich.progress import Progress, TextColumn, BarColumn, DownloadColumn, TransferSpeedColumn, TimeRemainingColumn
from torrent import TorrentFile
from tracker import TrackerClient
from peer import PeerConnection
from piece import PieceManager
from file_manager import FileManager

console = Console()

class TorrentEngine:
    def __init__(self, torrent_path, download_dir):
        self.torrent_path = torrent_path
        self.download_dir = download_dir
        self.torrent = None
        self.tracker = None
        self.piece_manager = None
        self.peers = []
        self.active_connections = []

    async def start(self):
        console.print("[bold magenta][*] Starting Torrent Engine...[/bold magenta]\n")
        
        try:
            self.torrent = TorrentFile(self.torrent_path)
            file_manager = FileManager(self.torrent, self.download_dir)
            self.piece_manager = PieceManager(self.torrent, file_manager) 
        except Exception as e:
            import traceback
            console.print(f"[bold red][-] Fatal error during initialization: {e}[/bold red]")
            traceback.print_exc()
            return
            
        self.tracker = TrackerClient(self.torrent)
        self.peers = await self.tracker.get_peers()
        
        if not self.peers:
            console.print("[bold red][-] No peers found. Cannot continue download.[/bold red]")
            return
            
        console.print("\n[bold magenta][*] Initiating Peer Wire Protocol...[/bold magenta]\n")

        # Phase 3: UI, Connecting, Downloading, and Seeding
        try:
            # The 'try' block now wraps the ENTIRE Progress context manager
            with Progress(
                TextColumn("[bold blue]{task.description}", justify="right"),
                BarColumn(bar_width=None),
                "[progress.percentage]{task.percentage:>3.1f}%",
                "•",
                DownloadColumn(),
                "•",
                TransferSpeedColumn(), 
                "•",
                TimeRemainingColumn(),
            ) as progress:

                download_task = progress.add_task("Downloading", total=self.torrent.total_length)
                
                # Connect to peers concurrently
                no_of_peers = 30
                for ip, port in self.peers[:no_of_peers]: 
                    asyncio.create_task(self._connect_and_run(ip, port))

                # Phase 1: Downloading
                loop_counter = 0
                while self.piece_manager.downloaded_bytes < self.torrent.total_length:
                    progress.update(download_task, completed=self.piece_manager.downloaded_bytes)
                    await asyncio.sleep(0.1) 
                    
                    # ENDGAME FIX: Every 5 seconds, reset stuck pending blocks!
                    loop_counter += 1
                    if loop_counter >= 50:
                        self.piece_manager.reset_pending_blocks()
                        loop_counter = 0
                    
                # Force bar to 100% 
                progress.update(download_task, completed=self.torrent.total_length)
                
            # --- PROGRESS BAR IS DESTROYED HERE ONCE THE 'WITH' BLOCK ENDS ---
            
            console.print("\n[bold green][*] Download Complete![/bold green]")
            console.print("[bold cyan][*] Transitioning to SEEDING phase... (Press Ctrl+C to stop)[/bold cyan]")
            
            # Phase 2: Seeding
            while True:
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            console.print("\n[bold yellow][*] Process aborted by user.[/bold yellow]")
            pass

    # Asynchronous peer run
    async def _connect_and_run(self, ip, port):
        peer = PeerConnection(ip, port, self.torrent.info_hash, self.tracker.peer_id, self.piece_manager)
        success = await peer.connect_and_handshake()
        
        if success:
            self.active_connections.append(peer)
            # Non-blocking data listening
            await peer.message_loop()