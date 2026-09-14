# Encryption constants (extracted from desktop version utils/constants.py)
EVF_MAGIC = b"EVF1"
EVF_VERSION = 1
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for streaming
SALT_SIZE = 32
NONCE_SIZE = 12
TAG_SIZE = 16

# Argon2 parameters
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

ENCRYPTED_EXTENSION = ".evf"
