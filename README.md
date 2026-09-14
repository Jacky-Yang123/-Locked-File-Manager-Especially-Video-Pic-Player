# 🛡️ Locked File Manager

**面向隐私的加密媒体管理与播放系统** —— 用 `AES-256-GCM + Argon2id` 把视频 / 图片 / PDF / 文本封装成自定义容器 `.evf`，再通过桌面端、Web 端、局域网共享三种形态消费它。

[中文](#-中文) | [English](#-english)

---

## 🇨🇳 中文

### 这是什么

一个「**加密在磁盘上，解密在内存里**」的媒体库。文件落盘时是密文，播放/浏览时流式解密，**全程不产生任何临时明文文件**。

三端复用同一套 `.evf` 格式与同一套密钥派生，因此密文互通：

| 形态 | 入口 | 典型场景 |
|---|---|---|
| 💻 **PC 客户端** | `python main.py`（PyQt6） | 本机媒体库、批量加密/解密、4K / VR 全景播放 |
| 🌐 **Web 服务端** | `web/app.py`（Flask） | 手机 / 浏览器远程浏览 NAS（WebDAV / SMB）或本机目录 |
| 📡 **局域网共享** | PC 客户端内「网络共享」 | 把本机文件夹以 **WebDAV + Web UI 双栈**暴露给同网段设备 |

### ✨ 核心特性

**安全**

- `AES-256-GCM` 分块加密，**每块独立 nonce** → 支持随机 seek，进度条可随意拖动
- `Argon2id` 密钥派生（`time=3 / memory=64MiB / parallelism=4`），抗 GPU 暴力破解
- **流式解密**：明文只在内存中出现，磁盘上零明文残留（含缩略图）
- 缩略图同样加密存储（`*.enc`），无法通过缩略图反推原内容
- 本机元数据（播放历史、共享配置）用机器密钥加密，访问日志只记 `sha256(路径)[:12]`

**功能**

- 视频 / 图片 / PDF / 文本 / 音频全覆盖；加密 PDF 按页服务端渲染
- **4K VR 全景**：OpenGL 与 WebEngine 双内核，支持 180°/360°
- 局域网共享内置**自签 TLS**，凭据与解密后的视频流都不走明文 HTTP
- Web UI 移动端适配：双指缩放、触摸手势、一键跳转 VLC / nPlayer / PotPlayer
- 与 **4XVR**、**ES 文件浏览器**、**VLC** 等 WebDAV 客户端实测兼容
- 待机模式：进入后自动隐藏控制面板

### 📦 `.evf` 容器格式

```
偏移   长度   内容
0      4      Magic "EVF1"
4      2      Version (uint16 LE)
6      32     Salt (Argon2id)
38     4      Chunk Size (uint32 LE, 1 MiB)
42     8      Original Size (uint64 LE)
50     16     Original Ext (ASCII, 如 ".mp4")
66     4      Num Chunks (uint32 LE)
70     ...    分块数据 = 12B nonce + 密文 + 16B GCM tag
```

- 头部共 **70 字节**且**明文可读** —— 列表页、缩略图、虚拟命名靠它拿到原始大小与扩展名，无需密码。
- 原始扩展名**只存在头部**，不在文件名里：磁盘上是 `IMG_6304.evf`，对外虚拟化为 `IMG_6304.mp4`。
- 支持**混合容器**：`[正常图片字节][EVF 数据][偏移][MAGIC]`，既能当普通图片看，内容又是加密的。

### 🚀 快速开始

**环境**：Python 3.10+（Windows 用户注意：请确保 `pycryptodome` 已装，否则 `import Crypto` 会失败）

```bash
# PC 客户端
pip install -r requirements.txt
python main.py

# Web 服务端（独立运行）
cd web
pip install -r requirements.txt
python app.py          # 或双击 run_server.bat

# 打包成单文件 exe
python build_release.py
```

**局域网共享**：PC 客户端 → 「网络共享」→ 选目录 → 设密码 →（可选）启用 HTTPS → 启动。默认端口 `8080`。

```bash
# 浏览器访问 UI
https://<本机IP>:8080/

# WebDAV 客户端 / VLC / ffprobe 直接取流
https://<本机IP>:8080/<文件名>.mp4
```

### 📁 项目结构

```
core/    跨形态共享的加密与业务层（.evf 格式、加解密引擎、WebDAV 处理器、共享服务）
ui/      PC 客户端界面（PyQt6）
utils/   常量、路径工具、HTTP Range 解析、Windows 长路径容错
web/     Flask 子项目（远端/本机存储浏览 + 流式播放 + 缩略图）
HANDOVER.md   ★ 交接文档：架构地图、完整路由表、数据库结构、9 条已知坑、自测方法
```

### 🔐 安全模型与已知限制

| 面 | 做法 |
|---|---|
| WebDAV 认证 | Basic / Bearer 双支持，值 = `base64("user:pass")`；媒体标签额外支持 `?token=` |
| 口令比较 | `hmac.compare_digest`（防时序侧信道） |
| 暴力破解 | 每 IP 60 秒内 5 次失败 → `429` |
| 路径穿越 | `realpath` + 根目录包含性双重校验 |

**限制**（按"只读浏览 + 删除"的定位设计）：

- 自签证书需客户端手动信任，浏览器会报"链接不安全"——这是**预期行为**。
- 共享仅靠单一密码，无 per-user 账号体系。
- WebDAV 只实现 `DELETE`，未实现 `MKCOL / MOVE / COPY / PROPPATCH`。

### 🧪 自测

```bash
python _dav_selftest.py ; echo "exit=$?"
# 期望：31/31 passed
```

覆盖 PROPFIND 各层级、中文/空格/括号文件名、>260 字符深路径、三种 HTTP Range 形式、`?token=` 认证、路径穿越拦截，并用 `ffprobe` 真实验证解密流（含 moov 在尾部的 non-faststart MP4——即"视频打不开"的原始场景）。

---

## 🇬🇧 English

### What it is

A privacy-first encrypted media library. Files live on disk as ciphertext and are **decrypted on the fly into memory** — **no temporary plaintext file is ever written**.

All three surfaces share the same `.evf` container format and key derivation, so ciphertext is interchangeable:

| Surface | Entry point | Use case |
|---|---|---|
| 💻 **Desktop client** | `python main.py` (PyQt6) | Local library, batch encrypt/decrypt, 4K / VR 360° playback |
| 🌐 **Web server** | `web/app.py` (Flask) | Browse a NAS (WebDAV / SMB) or a local folder from phone or browser |
| 📡 **LAN sharing** | "Network Share" in the desktop app | Expose a local folder over **WebDAV + Web UI on one port** |

### ✨ Highlights

**Security**

- `AES-256-GCM`, per-chunk independent nonce → random seek works, scrubbing is smooth
- `Argon2id` key derivation (`time=3 / memory=64MiB / parallelism=4`)
- Streaming decryption — plaintext exists only in memory; encrypted thumbnails too
- Machine-key encrypted local metadata; access logs store `sha256(path)[:12]` only

**Features**

- Video / image / PDF / text / audio; encrypted PDFs rendered page-by-page server-side
- **4K VR** with dual OpenGL + WebEngine kernels (180°/360°)
- Built-in **self-signed TLS** for LAN sharing — credentials and streams never travel in cleartext
- Verified against **4XVR**, **ES File Explorer**, **VLC** as WebDAV clients
- Mobile-optimized Web UI with pinch-to-zoom and one-tap handoff to VLC / nPlayer / PotPlayer

### 📦 The `.evf` format

See the byte layout above. The **70-byte header is plaintext** (by design) so listings, thumbnails and virtual naming can read original size and extension without a password. The original extension lives **only in the header**, not in the filename: `IMG_6304.evf` on disk is presented as `IMG_6304.mp4`.

### 🚀 Quick start

```bash
# Desktop client
pip install -r requirements.txt
python main.py

# Web server
cd web && pip install -r requirements.txt && python app.py

# Build a single-file exe
python build_release.py
```

### 📖 Docs

Architecture map, full route tables, database schema, known pitfalls and self-test instructions live in **`HANDOVER.md`**.

### ⚠️ Known limitations

Self-signed certificate must be trusted manually (the "not secure" warning is expected). Single shared password, no per-user accounts. WebDAV implements `DELETE` only.

---

## 📝 License

私有软件 / 个人使用 — Proprietary / Personal Use.
