import os

class FileManager:
    def __init__(self, torrent, download_dir):
        self.torrent = torrent
        self.download_dir = download_dir
        self._create_files()

    def _create_files(self):
        """Pre-allocates empty files on the hard drive."""
        os.makedirs(self.download_dir, exist_ok=True)
        
        for file_info in self.torrent.files:
            file_path = os.path.join(self.download_dir, file_info['path'])
            
            # Create subdirectories if needed (for multi-file torrents)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Create an empty file of the exact target size
            if not os.path.exists(file_path):
                with open(file_path, 'wb') as f:
                    f.truncate(file_info['length'])

    def write_piece(self, piece_index, piece_data):
        """Writes a verified piece of data to the correct file(s) on disk."""
        # Calculate exactly where this piece starts in the overall torrent
        global_offset = piece_index * self.torrent.piece_length
        current_file_offset = 0
        
        for file_info in self.torrent.files:
            file_length = file_info['length']
            file_path = os.path.join(self.download_dir, file_info['path'])
            
            # Check if this piece overlaps with this specific file
            if global_offset < current_file_offset + file_length and global_offset + len(piece_data) > current_file_offset:
                # Calculate the exact byte positions
                file_seek = max(0, global_offset - current_file_offset)
                data_offset = max(0, current_file_offset - global_offset)
                write_length = min(file_length - file_seek, len(piece_data) - data_offset)
                
                # Write the binary data to the disk!
                with open(file_path, 'r+b') as f:
                    f.seek(file_seek)
                    f.write(piece_data[data_offset:data_offset + write_length])
                    
            current_file_offset += file_length

    def read_piece(self, piece_index, expected_length):
        """Reads a piece from disk to check if it already exists."""
        global_offset = piece_index * self.torrent.piece_length
        current_file_offset = 0
        piece_data = bytearray()
        
        for file_info in self.torrent.files:
            file_length = file_info['length']
            file_path = os.path.join(self.download_dir, file_info['path'])
            
            # Check if this piece overlaps with this specific file
            if global_offset < current_file_offset + file_length and global_offset + expected_length > current_file_offset:
                file_seek = max(0, global_offset - current_file_offset)
                read_length = min(file_length - file_seek, expected_length - len(piece_data))
                
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        f.seek(file_seek)
                        piece_data.extend(f.read(read_length))
                else:
                    return None # File doesn't exist yet
                    
            current_file_offset += file_length
            
        if len(piece_data) == expected_length:
            return bytes(piece_data)
        return None