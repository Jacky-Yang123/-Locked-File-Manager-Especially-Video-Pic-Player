"""
Constants and configuration for the encrypted video player.
"""

# Application info
APP_NAME = "Locked Video Player"
APP_VERSION = "2.0.0"

# Encryption constants
EVF_MAGIC = b"EVF1"
EVF_VERSION = 1
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for streaming
SALT_SIZE = 32
NONCE_SIZE = 12
TAG_SIZE = 16

# Argon2 parameters (memory-hard for anti-brute-force)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536  # 64MB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32

# Supported file formats
SUPPORTED_VIDEO_FORMATS = [
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", 
    ".webm", ".m4v", ".mpeg", ".mpg", ".3gp", ".ts"
]

SUPPORTED_IMAGE_FORMATS = [
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"
]

SUPPORTED_AUDIO_FORMATS = [
    ".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a", ".wma", ".opus"
]

SUPPORTED_TEXT_FORMATS = [
    ".txt", ".md", ".log", ".json", ".xml", ".ini", ".cfg", ".conf",
    ".py", ".c", ".cpp", ".h", ".java", ".js", ".css", ".html", ".sh", ".bat"
]

SUPPORTED_DOCUMENT_FORMATS = [
    ".pdf"
]

# Encrypted file extension
ENCRYPTED_EXTENSION = ".evf"

# UI Constants
WINDOW_MIN_WIDTH = 1200
WINDOW_MIN_HEIGHT = 700

# Playback speeds
PLAYBACK_SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 3.0, 4.0]
