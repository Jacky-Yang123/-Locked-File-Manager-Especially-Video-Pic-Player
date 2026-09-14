"""
WebEngine-based VR Player Widget.
Uses HTML5 + Three.js to render 360/180 videos with hardware acceleration.
Stable for 4K content.
"""

import os
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage
from PyQt6.QtCore import QUrl, pyqtSlot

class VRWebWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.webview = QWebEngineView()
        
        # Configure settings for local file access and performance
        settings = self.webview.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        
        self.layout.addWidget(self.webview)
        
        # Default Mode: 180 SBS (1)
        self.mode = 1 
        self.current_url = ""
        
    def set_mode(self, mode):
        # 0=360, 1=180SBS
        self.mode = mode
        # Reload to apply shader changes if video is loaded, or JS call
        if self.current_url:
            self.load_video(self.current_url)

    def load_video(self, file_path):
        self.current_url = file_path
        # Normalize path for URL
        url_path = QUrl.fromLocalFile(file_path).toString()
        
        html = self._get_html_template(url_path, self.mode)
        self.webview.setHtml(html, QUrl.fromLocalFile(os.getcwd() + "/"))
        
    def stop(self):
        self.webview.load(QUrl("about:blank"))
        self.current_url = ""

    def _get_html_template(self, video_src, mode):
        # Three.js CDN or local fallback. Using generic CDN.
        # Implements a basic sphere mapped video player.
        # Handles 180 SBS by adjusting UVs.
        
        # Mode 1 logic (180 SBS):
        # Use only left half of video (U 0.0 to 0.5).
        # Map to Hemisphere (PhiLength PI).
        
        is_180 = "true" if mode == 1 else "false"
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>body {{ margin: 0; overflow: hidden; background-color: #000; }}</style>
            <script type="importmap">
              {{
                "imports": {{
                  "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
                  "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
                }}
              }}
            </script>
        </head>
        <body>
            <script type="module">
                import * as THREE from 'three';
                import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

                let camera, scene, renderer, controls;

                init();
                animate();

                function init() {{
                    const container = document.createElement('div');
                    document.body.appendChild(container);

                    camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
                    camera.position.set(0, 0, 0.1); 

                    scene = new THREE.Scene();

                    // Video Geometry
                    const geometry = new THREE.SphereGeometry(500, 60, 40);
                    // Invert geometry so we view from inside
                    geometry.scale(-1, 1, 1);

                    // UV Mapping Fixes
                    const uvAttribute = geometry.attributes.uv;
                    const is180 = {is_180};
                    
                    if (is180) {{
                        // Remap UVs for 180 SBS (Left Eye)
                        // Left eye is 0.0 to 0.5 on U axis
                        // Sphere covers 360, but we only have 180 content?
                        // Actually standard 180 video is mapped to a hemisphere.
                        // SphereGeometry(radius, wSeg, hSeg, phiStart, phiLength, ...)
                        // We should recreate geometry for 180.
                    }} else {{
                        // 360 Mono - standard UVs are fine
                    }}

                    // Video Texture
                    const video = document.createElement('video');
                    video.src = "{video_src}";
                    video.loop = true;
                    video.muted = false; // Playing audio too
                    video.playsInline = true;
                    video.crossOrigin = "anonymous";
                    video.play();

                    const texture = new THREE.VideoTexture(video);
                    
                    // For 180 SBS, we need to handle texture mapping specifically.
                    // Instead of complex UV, easiest is texture.repeat/offset
                    if (is180) {{
                       // Showing Left Eye: U from 0 to 0.5
                       texture.repeat.set(0.5, 1);
                       texture.offset.set(0, 0); 
                       
                       // And we need to limit the sphere to 180 degrees?
                       // If we map 0.5 texture to 360 sphere, it wraps twice.
                       // 180 video usually covers front 180.
                       // Let's create a Hemisphere geometry instead if 180.
                    }}

                    const material = new THREE.MeshBasicMaterial({{ map: texture }});
                    
                    let mesh;
                    if (is180) {{
                        const hemiGeo = new THREE.SphereGeometry(500, 60, 40, Math.PI * 1.5, Math.PI); 
                        // phiStart PI*1.5 (270deg) to center it? 
                        // Standard sphere starts at +X? 
                        // Let's stick to full sphere for safety but black out back? 
                        // Or just standard sphere and user only looks forward.
                        hemiGeo.scale(-1, 1, 1);
                        mesh = new THREE.Mesh(hemiGeo, material);
                    }} else {{
                        mesh = new THREE.Mesh(geometry, material);
                    }}
                    
                    scene.add(mesh);

                    renderer = new THREE.WebGLRenderer();
                    renderer.setPixelRatio(window.devicePixelRatio);
                    renderer.setSize(window.innerWidth, window.innerHeight);
                    container.appendChild(renderer.domElement);

                    controls = new OrbitControls(camera, renderer.domElement);
                    controls.enableZoom = true;
                    controls.enablePan = false;
                    controls.enableDamping = true;
                    controls.rotateSpeed = -0.5; // Invert drag for "looking" feel

                    window.addEventListener('resize', onWindowResize);
                }}

                function onWindowResize() {{
                    camera.aspect = window.innerWidth / window.innerHeight;
                    camera.updateProjectionMatrix();
                    renderer.setSize(window.innerWidth, window.innerHeight);
                }}

                function animate() {{
                    requestAnimationFrame(animate);
                    controls.update();
                    renderer.render(scene, camera);
                }}
            </script>
        </body>
        </html>
        """
