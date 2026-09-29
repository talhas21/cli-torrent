import hashlib
import bencode
from rich.console import Console

console = Console()

class TorrentFile:
    def __init__(self, file_path):
        self.file_path = file_path
        self.meta_info = None
        self.announce_url = None
        self.info_hash = None
        self.piece_length = 0
        self.piece_hashes = []
        self.total_length = 0
        self.files = []  # List of dicts containing {'path': something, 'length': something}
        
        self._load_and_parse()

    def _load_and_parse(self):
        console.print(f"[bold blue][*][/bold blue] Reading torrent metadata from {self.file_path}...")
        
        try:
            with open(self.file_path, 'rb') as f:
                torrent_data = f.read()
            
            # Decode bencoded file
            self.meta_info = bencode.decode(torrent_data)
            
            # 1. Extract Tracker URL
            self.announce_url = self.meta_info.get('announce', '')
            
            info_dict = self.meta_info['info']

            # Check for v2 or Hybrid protocol
            if 'meta version' in info_dict and info_dict['meta version'] == 2:
                if 'pieces' not in info_dict:
                    # It's a strict v2 torrent (no v1 fallback)
                    console.print("[bold red][-[/bold red]] Error: This is a strict BitTorrent v2 torrent.")
                    console.print("[bold red][-[/bold red]] This client currently only supports v1 and Hybrid torrents.")
                    raise NotImplementedError("BitTorrent v2 not supported yet.")
                else:
                    # It's a Hybrid torrent, we can proceed using the v1 data
                    console.print("[bold yellow][!][/bold yellow] Hybrid v1/v2 torrent detected. Defaulting to v1 protocol.")

            self.piece_length = info_dict['piece length']
            
            # 2. Calculate unique Info Hash
            raw_info = bencode.encode(info_dict)
            self.info_hash = hashlib.sha1(raw_info).digest()
            
            # 3. Handle Single-File vs Multi-File structures
            if 'files' in info_dict: 
                # Multi-file torrent
                for f in info_dict['files']:
                    path = "/".join(f['path'])
                    length = f['length']
                    self.files.append({'path': path, 'length': length})
                    self.total_length += length
            else:
                # Single-file torrent
                path = info_dict['name']
                length = info_dict['length']
                self.files.append({'path': path, 'length': length})
                self.total_length = length

            # 4. Parse the massive piece hashes byte-string into 20-byte chunks
            raw_pieces = info_dict['pieces']
            # If the library decoded it to a string by accident, we must encode it back to raw bytes
            if isinstance(raw_pieces, str):
                raw_pieces = raw_pieces.encode('latin1')
            self.piece_hashes = [raw_pieces[i:i+20] for i in range(0, len(raw_pieces), 20)]
            
            # Success messaging using Rich styling
            console.print("[bold green][+][/bold green] Torrent parsed successfully.")
            console.print(f"    [dim]- Tracker:[/dim] {self.announce_url}")
            console.print(f"    [dim]- Total Size:[/dim] {self.total_length / (1024*1024):.2f} MB")
            console.print(f"    [dim]- Total Pieces:[/dim] {len(self.piece_hashes)}")
            
        except FileNotFoundError:
            console.print(f"[bold red][-][/bold red] Error: File not found at {self.file_path}")
            raise
        except Exception as e:
            console.print(f"[bold red][-][/bold red] Failed to parse torrent file: [yellow]{e}[/yellow]")
            raise