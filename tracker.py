import aiohttp
import bencode
import urllib.parse
import struct
import socket
import hashlib
from rich.console import Console

console = Console()

class TrackerClient:
    def __init__(self, torrent):
        self.torrent = torrent
        # Generate a unique 20-byte Peer ID to identify our client to the tracker
        self.peer_id = b'-PT0001-' + hashlib.sha1(b'my_unique_id').digest()[:12]
        self.port = 6881 # Standard BitTorrent TCP port
        self.peers = []

    async def get_peers(self):
        """Sends a request to the tracker and decodes the peer list."""
        console.print(f"\n[bold blue][*][/bold blue] Contacting Tracker: [cyan]{self.torrent.announce_url}[/cyan]")
        
        # Build the exact parameters required by the BitTorrent Protocol
        params = {
            'info_hash': self.torrent.info_hash,
            'peer_id': self.peer_id,
            'port': self.port,
            'uploaded': 0,
            'downloaded': 0,
            'left': self.torrent.total_length,
            'compact': 1,  # Request the efficient 6-byte binary peer format
            'event': 'started'
        }

        # URL encode the parameters (critical for the raw bytes in info_hash)
        url = self.torrent.announce_url + '?' + urllib.parse.urlencode(params)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status != 200:
                        console.print(f"[bold red][-[/bold red]] Tracker returned HTTP {response.status}")
                        return []
                    
                    response_data = await response.read()
                    return self._parse_tracker_response(response_data)
                    
        except Exception as e:
            console.print(f"[bold red][-[/bold red]] Failed to connect to tracker: [yellow]{e}[/yellow]")
            return []

    def _parse_tracker_response(self, response_data):
        """Decodes the bencoded response and unpacks the compact peer IP/Ports."""
        try:
            tracker_dict = bencode.decode(response_data)
            
            # Check if tracker sent a failure message
            if 'failure reason' in tracker_dict:
                console.print(f"[bold red][-[/bold red]] Tracker error: {tracker_dict['failure reason']}")
                return []

            raw_peers = tracker_dict.get('peers', b'')
            
            # Convert to bytes if the library erroneously decoded it to a string
            if isinstance(raw_peers, str):
                raw_peers = raw_peers.encode('latin1')

            # Unpack the 6-byte chunks (4 bytes IP, 2 bytes Port)
            for i in range(0, len(raw_peers), 6):
                # Ensure we have exactly 6 bytes to unpack
                if len(raw_peers[i:i+6]) == 6:
                    # ! = Network byte order (Big-Endian), 4s = 4-byte string, H = unsigned short (port)
                    ip_bytes, port = struct.unpack('!4sH', raw_peers[i:i+6])
                    ip_address = socket.inet_ntoa(ip_bytes)
                    self.peers.append((ip_address, port))

            console.print(f"[bold green][+][/bold green] Received [magenta]{len(self.peers)}[/magenta] peers from tracker.")
            return self.peers

        except Exception as e:
            console.print(f"[bold red][-[/bold red]] Error parsing tracker response: {e}")
            return []