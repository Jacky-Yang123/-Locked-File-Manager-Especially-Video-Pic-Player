"""
File utilities for the encrypted video player.
"""

import os
from pathlib import Path
from typing import List, Optional
from utils.constants import (
    SUPPORTED_VIDEO_FORMATS, 
    SUPPORTED_IMAGE_FORMATS,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_TEXT_FORMATS,
    SUPPORTED_DOCUMENT_FORMATS,
    SUPPORTED_DOCUMENT_FORMATS,
    ENCRYPTED_EXTENSION
)
from core.evf_format import detect_mixed_file


def _check_extension(file_path: str, extensions: List[str]) -> bool:
    """Helper to check file extension."""
    ext = Path(file_path).suffix.lower()
    return ext in extensions


def is_video_file(file_path: str) -> bool:
    """Check if a file is a supported video format."""
    return _check_extension(file_path, SUPPORTED_VIDEO_FORMATS)


def is_image_file(file_path: str) -> bool:
    """Check if a file is a supported image format."""
    return _check_extension(file_path, SUPPORTED_IMAGE_FORMATS)


def is_audio_file(file_path: str) -> bool:
    """Check if a file is a supported audio format."""
    return _check_extension(file_path, SUPPORTED_AUDIO_FORMATS)


def is_text_file(file_path: str) -> bool:
    """Check if a file is a supported text format."""
    return _check_extension(file_path, SUPPORTED_TEXT_FORMATS)


def is_document_file(file_path: str) -> bool:
    """Check if a file is a supported document format (PDF, etc.)."""
    return _check_extension(file_path, SUPPORTED_DOCUMENT_FORMATS)


def is_pdf_file(file_path: str) -> bool:
    """Check if a file is a PDF file."""
    return Path(file_path).suffix.lower() == '.pdf'


def is_archive_file(file_path: str) -> bool:
    """Check if a file is a supported archive format."""
    ARCHIVE_EXTS = ['.zip', '.rar', '.7z', '.tar', '.gz', '.xz', '.bz2']
    return Path(file_path).suffix.lower() in ARCHIVE_EXTS


def is_supported_file(file_path: str) -> bool:
    """Check if file is any supported media type."""
    return (
        is_video_file(file_path) or
        is_image_file(file_path) or
        is_audio_file(file_path) or
        is_text_file(file_path) or
        is_document_file(file_path)
    )


def is_encrypted_file(file_path: str) -> bool:
    """Check if a file is an encrypted video file (.evf) or a mixed image."""
    ext = Path(file_path).suffix.lower()
    if ext == ENCRYPTED_EXTENSION:
        return True
    
    # Check for mixed format in images
    if ext in ['.jpg', '.jpeg', '.png']:
        return detect_mixed_file(file_path) >= 0
        
    return False


def get_supported_files(folder_path: str) -> List[str]:
    """Get all supported files in a folder (non-recursive)."""
    folder = Path(folder_path)
    if not folder.is_dir():
        return []
    
    files = []
    for file in folder.iterdir():
        if file.is_file():
            path = str(file)
            if is_supported_file(path) or is_encrypted_file(path):
                files.append(path)
    
    return sorted(files)

# Maintain backward compatibility alias
get_video_files = get_supported_files


def get_encrypted_files(folder_path: str) -> List[str]:
    """Get all encrypted files in a folder (non-recursive)."""
    folder = Path(folder_path)
    if not folder.is_dir():
        return []
        
    files = []
    for file in folder.iterdir():
        if file.is_file():
            path = str(file)
            if is_encrypted_file(path):
                files.append(path)
    return sorted(files)


def get_encrypted_output_path(input_path: str, output_folder: Optional[str] = None) -> str:
    """Generate output path for encrypted file."""
    input_file = Path(input_path)
    output_name = input_file.stem + ENCRYPTED_EXTENSION
    
    if output_folder:
        return str(Path(output_folder) / output_name)
    else:
        return str(input_file.parent / output_name)


def ensure_dir(path: str) -> None:
    """Ensure a directory exists, create if necessary."""
    Path(path).mkdir(parents=True, exist_ok=True)


def format_time(seconds: int) -> str:
    """Format seconds to HH:MM:SS or MM:SS."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
