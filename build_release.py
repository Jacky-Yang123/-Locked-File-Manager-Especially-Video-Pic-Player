
import os
import shutil
import PyInstaller.__main__
from pathlib import Path

def build():
    # Define build parameters
    app_name = "LockedVideoPlayer"
    entry_point = "main.py"
    
    # Icon path (if you have one, otherwise remove --icon)
    # icon_path = "assets/icon.ico" 
    
    # PyInstaller arguments
    args = [
        entry_point,
        '--name=%s' % app_name,
        '--noconsole',  # Hide console window
        '--onefile',    # Single exe
        '--clean',      # Clean cache
        
        # Add necessary data/imports
        # PyQt6 WebEngine often needs specific collection, but onefile tries to handle it.
        # If issues arise, we might need --collect-all PyQt6 or similar.
        '--collect-all=PyQt6', 
        '--collect-all=Crypto', # PyCryptodome
        
        # Exclude unnecessary modules to save size
        '--exclude-module=tkinter',
        '--exclude-module=matplotlib',
        
        # Add data files if any (Format: 'src;dest')
        '--add-data=assets;assets',
        '--add-data=web/templates;web/templates',
        '--add-data=web/static;web/static',
    ]
    
    print("🚀 Starting Build Process...")
    print(f"Target: {app_name}.exe")
    
    # Run PyInstaller
    PyInstaller.__main__.run(args)
    
    print("\n✅ Build Complete!")
    print(f"Executable is in the 'dist' folder: dist/{app_name}.exe")

if __name__ == "__main__":
    # Check if pyinstaller is installed
    try:
        import PyInstaller
        build()
    except ImportError:
        print("❌ PyInstaller not found. Installing...")
        os.system("pip install pyinstaller")
        build()
