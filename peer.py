import asyncio
import struct
import bitstring
from rich.console import Console

console = Console()

class PeerConnection:
    def __init__(self, ip, port, info_hash, my_peer_id, piece_manager):
        self.ip = ip
        self.port = port
        self.info_hash = info_hash
        self.my_peer_id = my_peer_id
        self.piece_manager = piece_manager
        
        self.reader = None
        self.writer = None
        self.connected = False
        
        # BitTorrent Protocol State (as defined in the spec)
        self.am_choking = True
        self.am_interested = False
        self.peer_choking = True
        self.peer_interested = False
        
        # Data the peer has
        self.bitfield = None

    async def connect_and_handshake(self):
        """Establishes TCP connection and performs the BitTorrent handshake."""
        try:
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.ip, self.port),
                timeout=5
            )
            
            pstr = b"BitTorrent protocol"
            pstrlen = bytes([len(pstr)]) 
            reserved = b'\x00' * 8
            handshake_req = pstrlen + pstr + reserved + self.info_hash + self.my_peer_id
            
            self.writer.write(handshake_req)
            await self.writer.drain()
            
            response = await asyncio.wait_for(self.reader.readexactly(68), timeout=5)
            
            peer_info_hash = response[28:48]
            if peer_info_hash != self.info_hash:
                return False
                
            #console.print(f"[bold green][+][/bold green] Successful handshake with {self.ip}:{self.port}")
            self.connected = True
            return True
            
        except Exception:
            return False

    async def message_loop(self):
        """Continuously listens for length-prefixed messages from the peer."""
        try:
            while self.connected:
                # 1. Read the length prefix (exactly 4 bytes)
                length_bytes = await self.reader.readexactly(4)
                
                # Unpack big-endian unsigned integer ('>I')
                message_length = struct.unpack('>I', length_bytes)[0]
                
                # 2. Handle Keep-Alive (length 0, no ID, no payload)
                if message_length == 0:
                    #console.print(f"[dim][{self.ip}] Received Keep-Alive[/dim]")
                    continue
                    
                # 3. Read the message ID (exactly 1 byte)
                id_byte = await self.reader.readexactly(1)
                message_id = id_byte[0]
                
                # 4. Read the payload (remaining bytes)
                payload_length = message_length - 1
                payload = b""
                if payload_length > 0:
                    payload = await self.reader.readexactly(payload_length)
                    
                # 5. Route the message to our handler
                await self._handle_message(message_id, payload)
                
        except asyncio.IncompleteReadError:
            pass
        except ConnectionResetError:
            pass
        except asyncio.TimeoutError:
            pass
        except ConnectionRefusedError:
            pass
        except Exception:
            pass
        finally:
            await self.close()

    async def _handle_message(self, message_id, payload):
        if message_id == 0:
            #console.print(f"[yellow][{self.ip}] Peer is CHOKING us.[/yellow]")
            self.peer_choking = True
            
        elif message_id == 1:
            #console.print(f"[bold green][{self.ip}] Peer UNCHOKED us![/bold green] (We can request data)")
            self.peer_choking = False
            
            # The moment we are unchoked, if we are interested, request the first 16KB block of Piece 0!
            if self.am_interested:
                # PIPELINING: Request 5 blocks at once instead of just 1!
                for _ in range(5):
                    await self.request_next_block()
            
        elif message_id == 4:
            pass 
            
        elif message_id == 5:
            self.bitfield = bitstring.BitArray(bytes=payload)
            
            safe_total = len(self.piece_manager.pieces)
            self.piece_manager.update_peer_bitfield(self.ip, self.bitfield[:safe_total])
            
            pieces_they_have = self.bitfield[:safe_total].count(1)
            
            #if pieces_they_have == safe_total:
                #console.print(f"[bold cyan][{self.ip}][/bold cyan] Peer is a SEED (Has 100% of pieces)")
                #pass
            #else:
                #console.print(f"[bold cyan][{self.ip}][/bold cyan] Peer has {pieces_they_have}/{safe_total} pieces")
                #pass
            
            await self.send_interested()
            
        elif message_id == 7:
            # WE GOT DATA! Unpack <index><begin><block>
            index = struct.unpack('>I', payload[:4])[0]
            begin = struct.unpack('>I', payload[4:8])[0]
            block_data = payload[8:]

            # Save the data to the manager's memory buffer
            piece = self.piece_manager.pieces[index]
            piece.save_block(begin, block_data)

            self.piece_manager.downloaded_bytes += len(block_data)

            if piece.is_complete():
                if piece.verify():
                    self.piece_manager.write_verified_piece(piece)
                    # Log successful verification to debug file
                    with open("debug.txt", "a") as f:
                        f.write(f"[+] SUCCESS! Piece {index} verified and written to disk.\n")
                else:
                    self.piece_manager.downloaded_bytes -= piece.length
                    piece.reset()
                    # Log hash failure to debug file
                    import hashlib
                    calculated = hashlib.sha1(piece.data).hexdigest()
                    expected = piece.piece_hash.hex()
                    with open("debug.txt", "a") as f:
                        f.write(f"[-] HASH MISMATCH! Piece {index} discarded.\nExpected: {expected}\nCalculated: {calculated}\n")
            
            # Keep the pipeline moving by instantly requesting the next block
            await self.request_next_block()

    async def request_next_block(self):
        """Asks the piece manager what to download next and sends the request."""
        request = self.piece_manager.get_next_request(self.ip)
        if request:
            index, offset, length = request
            # <len=0013><id=6><index><begin><length>
            msg = struct.pack('>IBIII', 13, 6, index, offset, length)
            self.writer.write(msg)
            await self.writer.drain()
        #else:
            #console.print(f"[dim][{self.ip}] No pieces needed from this peer right now.[/dim]")

    async def send_interested(self):
        #console.print(f"[dim][{self.ip}] Sending INTERESTED...[/dim]")
        # <len=0001><id=2>
        msg = struct.pack('>IB', 1, 2)
        self.writer.write(msg)
        await self.writer.drain()
        self.am_interested = True

        if not self.peer_choking:
            for _ in range(5):
                await self.request_next_block()

        
    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
        self.connected = False