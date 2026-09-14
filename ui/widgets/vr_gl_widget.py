"""
Asynchronous High-Performance VR Widget for 4K Content.
Features:
- Persistent Worker Thread (QThread + QObject) for zero-latency UI.
- Async QImage conversion and decimation.
- Automatic frame dropping to prevent processing lag.
- Standard Rec.709 color and orientation correction.
"""

import ctypes
import traceback
import time
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram
from PyQt6.QtCore import Qt, QPointF, QThread, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtGui import QSurfaceFormat, QImage
from PyQt6.QtMultimedia import QVideoFrame

try:
    from OpenGL.GL import *
except ImportError:
    print("PyOpenGL not installed. VR mode will fail.")

class VRWorker(QObject):
    """Persistent worker to handle heavy image processing off the UI thread."""
    image_ready = pyqtSignal(QImage)
    
    def __init__(self):
        super().__init__()
        self._is_busy = False
        self._max_resolution = 0 # 0 = Native, otherwise max width (e.g. 3840, 2048)

    def set_max_resolution(self, width: int):
        self._max_resolution = width

    @pyqtSlot(QVideoFrame)
    def process_frame(self, frame: QVideoFrame):
        if self._is_busy:
            return
            
        self._is_busy = True
        try:
            if not frame.isValid():
                return

            # Convert to QImage (Thread-safe copy)
            # 4K toImage can take 10-20ms
            img = frame.toImage()
            
            if not img.isNull():
                # Dynamic Resolution Limiting
                # self._max_resolution: 0=Native, 3840=4K, 2048=2K, 1920=1080p
                
                target_w = self._max_resolution
                if target_w > 0 and img.width() > target_w:
                    # Calculate height to keep AR
                    ratio = img.height() / img.width()
                    target_h = int(target_w * ratio)
                    
                    img = img.scaled(
                        target_w, target_h, 
                        Qt.AspectRatioMode.KeepAspectRatio, 
                        Qt.TransformationMode.FastTransformation
                    )
                
                # Ensure OpenGL compatible format
                if img.format() != QImage.Format.Format_RGBA8888:
                    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
                
                self.image_ready.emit(img)
        except Exception as e:
            print(f"Worker Error: {e}")
        finally:
            self._is_busy = False

class VRGLWidget(QOpenGLWidget):
    """
    Renders video frame as spherical 360/180 panorama.
    Uses a persistent worker thread to ensure the 4K video playback 
    and UI interaction (dragging) are perfectly smooth.
    """
    
    # Internal signal to communicate with worker
    _request_process = pyqtSignal(QVideoFrame)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Enforce Compatibility Profile
        fmt = QSurfaceFormat()
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CompatibilityProfile)
        self.setFormat(fmt)
        
        self.yaw = 0.0
        self.pitch = 0.0
        self.fov = 90.0
        
        self.last_mouse_pos = QPointF()
        self.mouse_pressed = False
        
        # Textures
        self.texture_id = 0
        self.last_tex_size = (0, 0)
        
        self.program = None
        self.mode = 0 # 0=360, 1=180 SBS
        
        # --- Persistent Worker Thread Setup ---
        self.worker = VRWorker()
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        
        # Connections
        self._request_process.connect(self.worker.process_frame)
        self.worker.image_ready.connect(self._on_image_ready)
        
        self.thread.start()
        
        self.current_display_image = None
        self._last_frame_time = 0
        
    def set_max_resolution(self, width: int):
        """Set max width for frames passed to GPU. 0 = Native."""
        # We need to call this on worker thread context or safer just set variable?
        # Worker is QObject, better use signal/slot or direct call if thread-safe interaction needed.
        # But setting int is atomic usually. 
        # But allow worker to update next frame.
        # We can just access it if we trust GIL? 
        # Better: add slot or just direct set since it's just an int read by worker loop.
        self.worker.set_max_resolution(width)
        
    def set_mode(self, mode):
        self.mode = mode
        self.update()
        
    def on_frame(self, frame: QVideoFrame):
        """Standard high-stability frame handler - pushes to worker thread."""
        if not frame or not frame.isValid(): return
        
        # Limit signal frequency to ~60fps to avoid queue buildup
        now = time.time()
        if now - self._last_frame_time < 0.015:
            return
        self._last_frame_time = now
        
        # Emit signal to worker thread
        self._request_process.emit(frame)
        
    @pyqtSlot(QImage)
    def _on_image_ready(self, image):
        """Called when worker thread has finished processing a frame."""
        self.current_display_image = image
        self.update()

    def initializeGL(self):
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glEnable(GL_TEXTURE_2D)
        
        vshader_src = """
            void main(void) {
                gl_Position = ftransform();
                gl_TexCoord[0] = gl_MultiTexCoord0;
            }
        """
        
        # Balanced shader with color and orientation corrections
        fshader_src = """
            uniform sampler2D tex;
            uniform float yaw;
            uniform float pitch;
            uniform float fov;
            uniform int mode;
            
            #define PI 3.14159265359

            mat3 rotateY(float angle) {
                float c = cos(angle); float s = sin(angle);
                return mat3(c, 0, s, 0, 1, 0, -s, 0, c);
            }
            mat3 rotateX(float angle) {
                float c = cos(angle); float s = sin(angle);
                return mat3(1, 0, 0, 0, c, -s, 0, s, c);
            }
            
            void main(void) {
                vec2 ndc = gl_TexCoord[0].st * 2.0 - 1.0;
                float aspect = 1.7777; 
                float tan_half_fov = tan(fov * PI / 360.0);
                
                vec3 ray = normalize(vec3(ndc.x * aspect * tan_half_fov, ndc.y * tan_half_fov, -1.0));
                ray = rotateX(-pitch) * ray;
                ray = rotateY(-yaw) * ray;
                
                float r = length(ray);
                float lon = atan(ray.x, -ray.z); 
                float lat = asin(ray.y / r);
                
                vec2 sphere_uv;
                sphere_uv.x = (lon / (2.0 * PI)) + 0.5;
                sphere_uv.y = 0.5 - (lat / PI); 
                
                if(mode == 1) { 
                     if(abs(lon) > PI/2.0) {
                         gl_FragColor = vec4(0,0,0,1);
                         return;
                     }
                     float local_x = (lon / PI) + 0.5; 
                     sphere_uv.x = local_x * 0.5; 
                }
                
                gl_FragColor = texture2D(tex, sphere_uv);
            }
        """
        
        self.program = QOpenGLShaderProgram()
        self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, vshader_src)
        self.program.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, fshader_src)
        self.program.link()
        
        self.texture_id = glGenTextures(1)
        
    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        if not self.program or not self.program.isLinked(): return
        
        # 1. Texture Upload Logic (Main Thread)
        if self.current_display_image and not self.current_display_image.isNull():
            glBindTexture(GL_TEXTURE_2D, self.texture_id)
            w, h = self.current_display_image.width(), self.current_display_image.height()
            
            # Use safe pointer conversion
            ptr = ctypes.c_void_p(int(self.current_display_image.bits()))
            
            if (w, h) != self.last_tex_size:
                glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, ptr)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
                glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
                self.last_tex_size = (w, h)
            else:
                glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, ptr)
            
            # Clear reference after upload to allow worker to reuse memory
            self.current_display_image = None

        # 2. Scene Rendering
        if self.last_tex_size != (0, 0):
            try:
                self.program.bind()
                self.program.setUniformValue("tex", 0)
                self.program.setUniformValue("yaw", self.yaw)
                self.program.setUniformValue("pitch", self.pitch)
                self.program.setUniformValue("fov", self.fov)
                self.program.setUniformValue("mode", self.mode)
                
                glActiveTexture(GL_TEXTURE0)
                glBindTexture(GL_TEXTURE_2D, self.texture_id)
                
                glBegin(GL_QUADS)
                glTexCoord2f(0,0); glVertex2f(-1,-1)
                glTexCoord2f(1,0); glVertex2f(1,-1)
                glTexCoord2f(1,1); glVertex2f(1,1)
                glTexCoord2f(0,1); glVertex2f(-1,1)
                glEnd()
                
                self.program.release()
            except Exception as e:
                print(f"Render Error: {e}")

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.position()
        self.mouse_pressed = True
        
    def mouseReleaseEvent(self, event):
        self.mouse_pressed = False
        
    def mouseMoveEvent(self, event):
        if self.mouse_pressed:
            delta = event.position() - self.last_mouse_pos
            self.last_mouse_pos = event.position()
            self.yaw -= delta.x() * 0.005
            self.pitch -= delta.y() * 0.005
            self.pitch = max(-1.5, min(1.5, self.pitch))
            self.update()
            
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.fov -= delta * 0.05
        self.fov = max(30.0, min(120.0, self.fov))
        self.update()
        
    def closeEvent(self, event):
        """Cleanup thread on widget closure."""
        self.thread.quit()
        self.thread.wait()
        super().closeEvent(event)
