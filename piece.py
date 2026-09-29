import math
import hashlib
from rich.console import Console 

console = Console()

BLOCK_SIZE = 16384  # 16KB standard BitTorrent block size

class Piece:
    def __init__(self, index, piece_hash, length):
        self.index = index
        self.piece_hash = piece_hash
        self.length = length
        
        # Calculate how many 16KB blocks are in this piece
        self.num_blocks = math.ceil(length / BLOCK_SIZE)
        
        # Track the state of each block: 0 = Missing, 1 = Pending, 2 = Complete
        self.blocks = [0] * self.num_blocks
        
        # Buffer to hold the raw binary data as it comes in
        self.data = bytearray(length)
        
    def get_missing_block(self):
        """Returns the index, offset, and length of the next needed block, or None."""
        for block_index, state in enumerate(self.blocks):
            if state == 0:  # If missing
                self.blocks[block_index] = 1  # Mark as pending
                
                offset = block_index * BLOCK_SIZE
                # The last block might be smaller than 16KB
                block_length = min(BLOCK_SIZE, self.length - offset)
                
                return self.index, offset, block_length
        return None

    def save_block(self, offset, data):
        """Saves downloaded bytes to the buffer and marks the block complete."""
        block_index = offset // BLOCK_SIZE
        self.blocks[block_index] = 2  # Mark as complete
        self.data[offset:offset+len(data)] = data

    def is_complete(self):
        """Checks if all blocks in this piece are downloaded."""
        return all(state == 2 for state in self.blocks)
    
    def verify(self):
        """Returns True if the downloaded data matches the expected SHA-1 hash."""
        calculated_hash = hashlib.sha1(self.data).digest()
        return calculated_hash == self.piece_hash

    def reset(self):
        """Resets the piece if the hash fails."""
        self.blocks = [0] * self.num_blocks
        self.data = bytearray(self.length)




class PieceManager:
    def __init__(self, torrent, file_manager):
        self.torrent = torrent
        self.file_manager = file_manager
        self.pieces = []
        self.peer_bitfields = {}  # Tracks what pieces each peer has { 'ip': bitfield }
        
        self.downloaded_bytes = 0

        self._initialize_pieces()
        self._check_resume_data()

    def _initialize_pieces(self):
        """Sets up all Piece objects based on the torrent metadata."""
        for i, piece_hash in enumerate(self.torrent.piece_hashes):
            # The very last piece in the torrent is almost always smaller than the standard piece length
            is_last_piece = (i == len(self.torrent.piece_hashes) - 1)
            if is_last_piece:
                # Calculate the exact remaining bytes
                piece_length = self.torrent.total_length % self.torrent.piece_length
                if piece_length == 0:
                    piece_length = self.torrent.piece_length
            else:
                piece_length = self.torrent.piece_length
                
            self.pieces.append(Piece(i, piece_hash, piece_length))

    def _check_resume_data(self):
        """Scans the disk on startup to see what pieces we already have."""
        console.print("[dim][*] Scanning disk for existing data to resume...[/dim]")
        
        for piece in self.pieces:
            piece_data = self.file_manager.read_piece(piece.index, piece.length)
            
            if piece_data:
                # Temporarily put data in piece buffer to run the hash verify method
                piece.data = bytearray(piece_data)
                
                if piece.verify():
                    # The hash matches! Mark all 16KB blocks in this piece as complete (2)
                    piece.blocks = [2] * piece.num_blocks
                    self.downloaded_bytes += piece.length
                    
                # Free memory (whether it passed or failed)
                piece.data = bytearray(piece.length)

    def update_peer_bitfield(self, ip, bitfield):
        """Stores or updates a peer's bitfield so we can calculate rarity."""
        self.peer_bitfields[ip] = bitfield

    def get_next_request(self, ip):
        """
        The Rarest First Algorithm.
        Finds the rarest missing piece that this specific peer has, 
        and returns the coordinates for the next block.
        """
        if ip not in self.peer_bitfields:
            return None

        peer_bitfield = self.peer_bitfields[ip]
        
        # 1. Calculate the rarity of all pieces across the entire swarm
        piece_counts = [0] * len(self.pieces)
        for bitfield in self.peer_bitfields.values():
            for i, has_piece in enumerate(bitfield):
                if has_piece:
                    piece_counts[i] += 1
                    
        # 2. Build a list of pieces that we still need, and that THIS peer actually has
        available_pieces = []
        for i, piece in enumerate(self.pieces):
            if not piece.is_complete() and peer_bitfield[i]:
                available_pieces.append( (i, piece_counts[i]) )
                
        if not available_pieces:
            return None # This peer has nothing we need right now
            
        # 3. Sort the available pieces by rarity (lowest count first)
        available_pieces.sort(key=lambda x: x[1])
        
        # 4. Iterate through the rarest pieces and find one with a missing block
        for piece_index, count in available_pieces:
            piece = self.pieces[piece_index]
            request = piece.get_missing_block()
            
            if request:
                return request # Returns (index, offset, block_length)
                
        return None

    def write_verified_piece(self, piece):
        """Writes to disk and clears the memory buffer."""
        self.file_manager.write_piece(piece.index, piece.data)
        # Clear the memory so we don't use gigabytes of RAM during big downloads
        piece.data = bytearray(0)

    def reset_pending_blocks(self):
        """Sweeps through and resets any pending blocks back to missing (0) so they can be re-requested."""
        for piece in self.pieces:
            if not piece.is_complete():
                for i in range(len(piece.blocks)):
                    if piece.blocks[i] == 1:
                        piece.blocks[i] = 0