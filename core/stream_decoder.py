import threading
import socket
from typing import Optional
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import urllib.parse

from core.crypto_engine import StreamingDecryptor
from core.evf_format import EVFHeader
from utils.range_utils import parse_range_header

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

class StreamDecoder:
    """
    Handles streaming decryption via local HTTP server.
    Supports Range requests for seeking.
    """
    
    def __init__(self):
        self._decryptor: Optional[StreamingDecryptor] = None
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port = 0
        self._header: Optional[EVFHeader] = None
        
    def open(self, source, password: str) -> str:
        """
        Start streaming server.
        Args:
            source: Path (str) or File-like object
            password: Decryption password
        Returns: URL
        """
        self._decryptor = StreamingDecryptor()
        self._header = self._decryptor.open(source, password)
        
        # Create Request Handler Closure to capture self
        decoder_instance = self
        
        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args): pass # Quiet
            
            def do_GET(self):
                # Simple path check
                if not self.path.startswith("/video"):
                    self.send_error(404)
                    return
                    
                total_size = decoder_instance.get_original_size()
                chunk_size = decoder_instance._header.chunk_size
                
                # Parse Range (shared helper: handles prefix / open / suffix forms)
                range_header = self.headers.get('Range')
                span = parse_range_header(range_header, total_size)
                if span is None:
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{total_size}')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                start, end = span
                length = end - start + 1
                
                self.send_response(206 if range_header else 200)
                
                # Guess correct MIME type so FFmpeg doesn't use the wrong demuxer
                ext = decoder_instance._header.original_ext.lower() if decoder_instance._header.original_ext else ".mp4"
                mime_type = 'video/mp4'
                if ext == '.mkv': mime_type = 'video/x-matroska'
                elif ext == '.webm': mime_type = 'video/webm'
                elif ext == '.avi': mime_type = 'video/x-msvideo'
                elif ext == '.mov': mime_type = 'video/quicktime'
                elif ext in ['.jpg', '.jpeg']: mime_type = 'image/jpeg'
                elif ext == '.png': mime_type = 'image/png'
                elif ext == '.mp3': mime_type = 'audio/mpeg'
                elif ext == '.flac': mime_type = 'audio/flac'
                elif ext == '.wav': mime_type = 'audio/x-wav'
                else: mime_type = 'application/octet-stream' # Let FFmpeg probe it
                
                self.send_header('Content-Type', mime_type)
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Range', f'bytes {start}-{end}/{total_size}')
                self.send_header('Content-Length', str(length))
                self.end_headers()
                
                # Stream Loop
                # Calculate start chunk
                current_pos = start
                
                try:
                    while current_pos <= end:
                        chunk_idx = current_pos // chunk_size
                        chunk_offset = current_pos % chunk_size
                        
                        # Get decrypted chunk
                        chunk_data = decoder_instance._decryptor.get_chunk_data(chunk_idx)
                        if not chunk_data: break
                        
                        # Slice content needed
                        available = len(chunk_data) - chunk_offset
                        send_amt = min(available, end - current_pos + 1)
                        
                        if send_amt <= 0: break
                        
                        data_to_send = chunk_data[chunk_offset : chunk_offset + send_amt]
                        self.wfile.write(data_to_send)
                        
                        current_pos += send_amt
                        
                except Exception as e:
                    # Client disconnected or decryption failed
                    if not isinstance(e, (ConnectionAbortedError, BrokenPipeError, ConnectionResetError)):
                        print(f"StreamDecoder streaming error: {e}")

        # Start Server on random port
        self._server = ThreadingHTTPServer(('127.0.0.1', 0), RequestHandler)
        self._port = self._server.server_port
        
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        
        ext = self._header.original_ext or ".mp4"
        return f"http://127.0.0.1:{self._port}/video{ext}"

    def wait_for_ready(self) -> bool:
        return self._server is not None
        
    def get_original_size(self) -> int:
        return self._header.original_size if self._header else 0
        
    def close(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._decryptor:
            self._decryptor.close()
            self._decryptor = None
