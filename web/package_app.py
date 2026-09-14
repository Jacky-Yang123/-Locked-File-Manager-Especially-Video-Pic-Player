import os
import glob
import zipfile

src_dir = 'G:/AI/player/web'
out_zip = 'G:/AI/player/web_deploy_package.zip'

excludes = ['venv', 'data', '__pycache__', '.pytest_cache', 'deploy_pkg', '.git', 'web_deploy_package.zip', 'package_app.py']

# Try to locate NAS deployment tutorial in common locations
tutorial_candidates = [
    'G:/AI/player/NAS部署教程.md',
    'G:/AI/player/web/NAS部署教程.md',
]
tutorial_candidates.extend(glob.glob('C:/Users/Jacky/.gemini/**/NAS部署教程.md', recursive=True))
tutorial_path = next((p for p in tutorial_candidates if os.path.exists(p)), None)

with zipfile.ZipFile(out_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [d for d in dirs if d not in excludes and not d.startswith('.')]

        for file in files:
            if file in excludes or file.endswith('.pyc') or file.endswith('.md'):
                continue

            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, src_dir)
            zipf.write(file_path, os.path.join('player_web', arcname))

    if tutorial_path:
        with open(tutorial_path, 'rb') as f:
            zipf.writestr('player_web/NAS部署教程.md', f.read())

    zipf.writestr('player_web/data/thumbnails/.gitkeep', b'')

print('Zip created successfully at', out_zip)
if tutorial_path:
    print('Included tutorial:', tutorial_path)
else:
    print('Warning: NAS部署教程.md not found, skipped.')
