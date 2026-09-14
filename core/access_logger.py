import logging
import os
import json
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

class AccessLogger:
    """
    Singleton logger for tracking network share access.
    Logs to 'access.log' in the application directory.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AccessLogger, cls).__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self):
        self.log_file = os.path.join(os.getcwd(), "access.log")
        self.logger = logging.getLogger("NetworkShareAccess")
        self.logger.setLevel(logging.INFO)
        
        # Avoid adding multiple handlers if setup is called multiple times (though singleton prevents init)
        if not self.logger.handlers:
            # Rotating file handler (1MB limit, 5 backup files)
            handler = RotatingFileHandler(self.log_file, maxBytes=1024*1024, backupCount=5, encoding='utf-8')
            formatter = logging.Formatter('%(message)s') # We store JSON, so raw message is best
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log_access(self, client_ip: str, action: str, resource: str):
        """
        Log an access event.
        :param client_ip: IP address of the client
        :param action: The action performed (e.g., "GET", "PROPFIND", "PLAY")
        :param resource: The file or path accessed (stored HASHED for privacy)
        """
        # Privacy: store a short hash of the resource instead of the raw path
        from core.secrets_store import sha256_short
        entry = {
            "timestamp": datetime.now().isoformat(),
            "ip": client_ip,
            "action": action,
            "resource_hash": sha256_short(resource or ""),
            "kind": Path(resource).suffix if resource else ""
        }
        try:
            self.logger.info(json.dumps(entry, ensure_ascii=False))
        except Exception as e:
            print(f"Failed to log access: {e}")

    def get_logs(self, limit=100) -> list:
        """
        Retrieve the latest logs.
        :param limit: Max number of logs to return
        :return: List of dicts
        """
        logs = []
        if not os.path.exists(self.log_file):
            return logs

        try:
            # Read file (it might be large, so ideally read from end, but for now simple readlines is okay for <1MB)
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            for line in reversed(lines): # Newest first
                if len(logs) >= limit:
                    break
                try:
                    if line.strip():
                        logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Error reading access log: {e}")
            
        return logs

    def clear_logs(self):
        """Clear the log file."""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write("")
        except Exception:
            pass
