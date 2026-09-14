# Locked File Manager — 项目交接文档

> 面向接手的 AI / 开发者。读完这一份应能：**跑起来 → 找到改的地方 → 不踩已知的坑 → 验证自己的改动**。
> 最后更新：2026-09-14（文末第 8 节的自测基线为当天实测复核结果）

---

## 0. 十分钟接管指南（先读这一节）

### 0.1 这台机器上怎么跑

```bash
# PC 客户端（PyQt6 桌面程序）
K:/Python312/python.exe main.py

# Web 子项目（Flask，扫 NAS / 本地目录）
cd web && ../K/Python312/python.exe app.py      # 等价写法见 3.2；或双击 web/run_server.bat

# 局域网共享：不单独起进程。从 PC 客户端「网络共享」对话框点启动
```

> ⚠️ **必须用 `K:/Python312/python.exe`（系统 Python 3.12）。**
> 托管 Python 3.13 没装 `pycryptodome`，直接跑会 `ModuleNotFoundError: No module named 'Crypto'`。

### 0.2 改完怎么验

```bash
K:/Python312/python.exe _dav_selftest.py ; echo "exit=$?"
```

期望输出末行 `31/31 passed`。**低于 31 就是回归。**（详见第 8 节）

### 0.3 三个"绝对不要"

1. **不要提交任何 `*.evf / *.enc / *.pem / *.key / library.* / share_configs.json / access.log / web/data/ / thumbnails/`** —— 全是用户隐私（真实路径、播放历史、机器密钥）。见第 9 节。
2. **不要给 UI 设置项加"人造下限"**（最小字号、最小透明度、token/图像上限等），用户对硬编码 cap 零容忍。
3. **不要只做静态检查就报"已修复"**。必须在真机/运行中的服务上自测，用 `✓ / ✗ / HTTP 码` 回话。

---

## 1. 一句话定位

一个**面向隐私的加密媒体管理与播放系统**：把本地的视频/图片/PDF/文本用 `AES-256-GCM + Argon2id` 封装成自定义容器 `.evf`，然后通过三种形态消费它——

| 形态 | 入口 | 面向场景 |
|---|---|---|
| 💻 PC 客户端 | `main.py`（PyQt6 桌面程序） | 本机管理库、加密、解密、4K/VR 播放 |
| 🌐 Web 服务端 | `web/app.py`（Flask） | 手机/浏览器远程浏览**远端存储**（WebDAV / SMB 的 NAS，或本机目录） |
| 📡 局域网共享 | PC 客户端内的「网络共享」（`core/network_share_server.py`） | 把**本机某个文件夹**以 WebDAV + Web UI 双栈暴露给同网段设备（VR 头显、ES 文件浏览器、VLC） |

三者**复用同一套 `.evf` 格式与同一套密钥派生**，因此密文互通。

### 1.1 为什么存在（设计动机）

用户住在新加坡合租房，路由器/房东层面存在流量监控与隐私暴露风险。因此产品有一条硬性要求：

- 局域网内的**任何**流（凭据、解密后的视频字节）都必须走 TLS，不能是明文 HTTP；
- 磁盘上不能留下任何解密后的临时明文文件（流式解密，只在内存里过）；
- 缩略图也必须加密存储，不能通过缩略图反推原内容。

---

## 2. 代码地图

```
G:\AI\player\
├─ main.py                          57    PC 客户端入口（PyQt6）
├─ requirements.txt                       PC 端依赖
├─ build_release.py                 56    PyInstaller 打包脚本
├─ _dav_selftest.py                       ★ WebDAV/共享服务端到端自测（31 项断言）
├─ .gitignore                             隐私排除清单（见第 9 节）
│
├─ core/                             # 【核心】跨形态共享的业务与加密层
│  ├─ evf_format.py                 169   .evf 容器格式（头读写、混合文件探测）
│  ├─ crypto_engine.py              515   EncryptionEngine / StreamingDecryptor
│  ├─ key_derivation.py              56   Argon2id 派生
│  ├─ webdav_server.py              616   ★ WebDAV 协议处理器（PROPFIND/GET/HEAD/OPTIONS/DELETE）
│  ├─ network_share_server.py      1894   ★ 局域网共享服务（WebDAV + Web UI + JSON API 同端口）
│  ├─ stream_decoder.py             140   本地回环播放服务（给 QtWebEngine/ffmpeg 喂流）
│  ├─ media_library.py              734   媒体库索引、缩略图生成（ThumbnailRunnable）
│  ├─ secrets_store.py              133   机器密钥 + 配置加解密
│  ├─ access_logger.py               89   访问日志（路径已脱敏为 hash+扩展名）
│  ├─ remote_stream.py               58   通过 HTTP Range 读远端文件的 file-like 对象
│  └─ cert_utils.py                      自签证书生成
│
├─ ui/                               # PC 客户端界面层（PyQt6）
│  ├─ main_window.py               1292   主窗口
│  ├─ network_share_dialog.py       637   ★ 共享设置：路径/端口/密码/HTTPS 开关
│  ├─ video_player.py               553   播放器（支持 VR 全景）
│  ├─ tools_dialog.py               757   工具集
│  ├─ encryption_dialog.py          406   加密对话框
│  ├─ decryption_dialog.py          427   解密对话框
│  ├─ access_log_dialog.py           85   访问日志查看（脱敏展示）
│  ├─ styles.py                     405   QSS 主题
│  └─ widgets/                           图片/PDF/文本查看器、VR、待机遮罩等
│
├─ utils/
│  ├─ constants.py                   54   ★ 全局常量（加密参数、支持格式、APP_VERSION）
│  ├─ file_utils.py                 154   路径/类型工具（含 get_encrypted_output_path）
│  ├─ range_utils.py                 77   ★ HTTP Range 统一解析（含 bytes=-N 后缀）
│  └─ win_paths.py                  110   ★ Windows 长路径（>260）容错读写/枚举
│
├─ assets/                               占位图 + 自签证书（lockedshare_cert.pem / lockedshare_key.pem）
│
└─ web/                              # Web 子项目（Flask，独立可跑）
   ├─ app.py                        659   Flask 入口、路由注册、后台扫描线程
   ├─ config.py                           配置
   ├─ package_app.py                      打包成 web_deploy_package.zip
   ├─ requirements.txt                    Web 端依赖（纯 ASCII）
   ├─ run_server.bat / run.bat            双击启动脚本
   ├─ services/
   │   ├─ auth.py                         JWT 认证、用户表、settings 读写
   │   ├─ storage_client.py               后端工厂（webdav / smb / local）
   │   ├─ webdav_client.py                WebDAV 客户端
   │   ├─ smb_client.py                   SMB 客户端
   │   ├─ local_client.py                 本机路径客户端
   │   ├─ stream_service.py               流会话 + PDF 逐页渲染 + Range
   │   └─ thumbnail_service.py            缩略图生成/加密存储
   ├─ static/js/                          app.js(文件浏览) / player.js(播放器) / viewer.js(图片·PDF·文本)
   ├─ templates/index.html                SPA 入口（★ 也被 PC 端共享服务的 UI 直接复用）
   ├─ data/                               运行时数据：app.db / thumbnails / cache（**永不入库**）
   └─ venv/                               子项目虚拟环境（**永不入库**）
```

**运行时会生成、绝不能提交的隐私文件**：
`library.json`（播放历史含真实路径）、`share_configs.json`（共享配置）、`library.key`（机器密钥）、
`thumbnails/*.enc`、`access.log`、`web/data/*`、`*.evf`、`*.pem`。

---

## 3. 环境与运行

### 3.1 依赖

PC 端 `requirements.txt`：
`PyQt6, PyQt6-WebEngine, PyOpenGL, opencv-python, pycryptodome, argon2-cffi, pymupdf`

Web 端 `web/requirements.txt`：
`flask, flask-cors, pyjwt, bcrypt, pycryptodome, argon2-cffi, requests, opencv-python-headless, PyMuPDF, smbprotocol`

### 3.2 三种启动方式

```bash
# ① PC 客户端
K:/Python312/python.exe main.py

# ② Web 子项目（独立跑，扫 NAS 或本机目录）
cd web
K:/Python312/python.exe app.py
#   或直接双击  web/run_server.bat（内部用 web/venv/Scripts/python.exe）

# ③ 局域网共享：不单独起进程
#    PC 客户端 → 「网络共享」→ 选目录 → 设密码 →（可选）勾 HTTPS → 启动
#    默认端口 8080
```

### 3.3 打包

```bash
K:/Python312/python.exe build_release.py
```

打包必须带这三条 `--add-data`（否则 exe 里前端和证书会缺）：

```
--add-data=assets;assets
--add-data=web/templates;web/templates
--add-data=web/static;web/static
```

代码里通过 `getattr(sys, '_MEIPASS', <源码目录>)` 解析资源，源码运行与打包运行**两种路径都要能命中**。

---

## 4. `.evf` 容器格式（三端互通的基础）

```
偏移   长度   内容
0      4      Magic "EVF1"
4      2      Version (uint16 LE, 当前 1)
6      32     Salt (Argon2id 用)
38     4      Chunk Size (uint32 LE, 固定 1 MiB)
42     8      Original Size (uint64 LE, 解密后字节数)
50     16     Original Ext (ASCII, 补 \x00, 例如 ".mp4")
66     4      Num Chunks (uint32 LE)
70     ...    分块数据，每块 = 12B nonce + 密文 + 16B GCM tag
```

- **头部共 70 字节**（`EVFHeader.HEADER_SIZE`），`original_ext` 字段在**偏移 50**——自测脚本造样本时直接改这两个位置。
- 密钥：`Argon2id(password, salt)`，参数 `time_cost=3 / memory_cost=65536(64MiB) / parallelism=4 / hash_len=32`（`utils/constants.py`）。
- 每块**独立 nonce**、独立 GCM tag；因此可以随机 seek 到任意块解密 → 这是流式播放/拖动进度条能工作的根本原因。
- **头部是明文的**：`read_evf_header()` 不需要密码就能拿到 `original_size / original_ext`。列表页、缩略图、虚拟命名都靠这个。

### 4.1 混合文件（mixed）

为了兼顾"能当普通图片看"和"内容是加密的"，图片可以做成混合容器：

```
[正常图片字节] [EVF 数据] [8B 偏移][11B MIXED_MAGIC]
```

`detect_mixed_file(path)` 从文件**尾部**探测并返回 EVF 起始偏移（找不到返回 `-1`）。
所以所有读取必须 `f.seek(offset)` 后再读头，**不能假设 EVF 从 0 开始**。

### 4.2 加密后的文件命名

`utils/file_utils.get_encrypted_output_path()`：

```python
output_name = input_file.stem + ".evf"      # video.mp4 -> video.evf
```

即**原始扩展名不体现在文件名里**，只存在头部。因此：

- 磁盘上是 `IMG_6304.evf`，头部 `original_ext=".mp4"`；
- 对外必须虚拟化成 `IMG_6304.mp4`。

真实库里也存在历史遗留的 `video.mp4.evf` 形态（早期版本命名），**两种都要能正确虚拟化**。

> ★ ★ **这是本项目最容易出错的地方，见第 7.2 节。**

---

## 5. 三条产品线架构

### 5.1 PC 客户端（PyQt6）

`main.py` → `ui/main_window.py`。职责：媒体库浏览、加密/解密、播放（视频/图片/PDF/文本/音频）、VR 全景、待机模式、网络共享管理。

播放链路：`core/stream_decoder.py` 起一个**本地回环 HTTP 服务**把 `.evf` 解密成流，交给 QtWebEngine / ffmpeg 播放——磁盘上不落地明文。

### 5.2 Web 子项目（Flask，`web/`）

面向**远端或本机存储**。通过 `services/storage_client.py` 工厂选择后端：

| `storage_type` | 客户端实现 | 说明 |
|---|---|---|
| `webdav` | `services/webdav_client.py` | 连 NAS 的 WebDAV，用 HTTP Range 按需读块 |
| `smb` | `services/smb_client.py` | 连 SMB 共享 |
| `local` | `services/local_client.py` | 直接读本机路径（让用户除了扫 NAS 也能指定本地加密目录） |

#### 5.2.1 路由表（`web/app.py` + `web/services/*.py`）

| 方法 | 路径 | 实现位置 |
|---|---|---|
| POST | `/api/auth/register` | `services/auth.py:129` |
| POST | `/api/auth/login` | `services/auth.py:159` |
| GET | `/api/auth/me` | `services/auth.py:179` |
| PUT | `/api/auth/account` | `services/auth.py:184` |
| GET / PUT | `/api/settings` | `services/auth.py:215 / 233` |
| GET | `/api/files/list` | `app.py:249` |
| GET | `/api/files/list_all` | `app.py:284` |
| POST | `/api/files/scan` | `app.py:326`（**异步**，立即返回 `scan_started`） |
| GET | `/api/files/scan_status` | `app.py:611`（前端每秒轮询） |
| GET | `/api/files/download_encrypted` | `app.py:410` |
| GET | `/api/files/download_decrypted` | `app.py:455` |
| GET | `/api/files/raw` | `app.py:508`（非加密文件直读代理） |
| POST | `/api/files/test-connection` | `app.py:576` |
| POST | `/api/stream/open` | `services/stream_service.py:252` |
| GET | `/api/stream/<sid>/video` | `services/stream_service.py:297` |
| POST | `/api/stream/<sid>/close` | `services/stream_service.py:315` |
| GET | `/api/preview/<sid>/pdf/info` | `services/stream_service.py:362` |
| GET | `/api/preview/<sid>/pdf/page/<n>` | `services/stream_service.py:377` |
| POST | `/api/thumbnails/generate_async` | `services/thumbnail_service.py:323` |
| GET | `/api/thumbnails/generate_status` | `services/thumbnail_service.py:383` |
| GET | `/api/thumbnails/<file_hash>` | `services/thumbnail_service.py:391` |
| GET | `/` · `/favicon.ico` | `app.py:634 / 639` |

#### 5.2.2 数据库（`web/data/app.db`，SQLite）

| 表 | 列 | 说明 |
|---|---|---|
| `users` | `id, username, password_hash, created_at` | 密码走 bcrypt |
| `user_settings` | `user_id, webdav_url, webdav_username, webdav_password, scan_path, storage_type, local_path` | `storage_type ∈ {webdav, smb, local}`；`local_path` 为本次新增列 |
| `file_index` | `id, user_id, parent_path, name, path, is_dir, size, mtime, ext` | 扫描结果，本机实测 2696 行 |
| `evf_metadata` | `file_hash, original_ext` | 本机实测 2704 行；缩略图缓存靠它反查扩展名 |

#### 5.2.3 扫描管线

- 后台线程 `run_background_scanner()` 每 5 分钟扫描一次，写 `file_index`。
- 进度通过 `scan_progress`（**按 `user_id` 隔离 + 线程锁**）暴露在 `/api/files/scan_status`，前端每秒轮询。
- 缩略图加密存 `web/data/thumbnails/*.jpg.enc`。
- 保存设置后前端自动触发一次 `/api/files/scan`，新用户不用等 5 分钟。

### 5.3 局域网共享（`core/network_share_server.py`，1894 行）

**一个端口同时提供三套协议栈**，靠 `RequestHandler.do_GET`（第 128 行起）分流：

```
/                      -> 内嵌 Web UI（读 web/templates/index.html）
/static/...            -> web/static 静态资源
/player?...            -> 独立播放页
/api/...               -> JSON API（见下表）
其它任意路径            -> super().do_GET() → WebDAV 文件服务
```

#### 5.3.1 路由表

**GET**（除 `/`、`/static/*`、`/api/auth/login`、`/favicon.ico` 外都需认证）：

| 路径 | 说明 |
|---|---|
| `/api/files/list` | 目录列举 |
| `/api/files/list_all` | 全库列举 |
| `/api/files/raw` | 非加密文件直读（支持 Range） |
| `/api/files/download_encrypted` | 下载原始 `.evf` |
| `/api/files/download_decrypted` | 下载解密流（密码走 `X-EVF-Password` 头） |
| `/api/files/scan` · `/api/files/scan_status` | 共享端固定返回空状态（不做扫描） |
| `/api/thumbnails/generate_status` | 后台缩略图生成进度 |
| `/api/thumbnails/<file_hash>` | 取缩略图（复用 PC 端 `thumbnails/` 缓存目录） |
| `/api/stream/open` | 开流会话 → 返回 `sid` |
| `/api/stream/<sid>/video` | 取解密流（支持 Range，`<video src>` 用） |
| `/api/stream/<sid>/close` | 关会话 |
| `/api/preview/<sid>/...` | 加密 PDF 逐页渲染 |
| `/api/auth/login` · `/api/auth/account` | 认证 / 账号信息 |
| `/api/settings` | 返回默认设置（共享端只读） |
| `/api/files` · `/api/file` · `/api/stream` · `/api/thumbnail` · `/api/nav` | **旧版兼容路由**，勿删 |

**POST**：`/api/unlock`、`/api/try_cached`、`/api/stream/open`、`/api/stream/<sid>/close`、`/api/auth/login`、`/api/files/scan`、`/api/thumbnails/generate_async`
**PUT**：接受并 no-op 返回 `{"status":"ok"}`（Web UI 会保存设置/账号，共享端不落盘）
**DELETE / PROPFIND / HEAD / OPTIONS**：父类 `WebDAVRequestHandler` 实现

#### 5.3.2 实现要点

- `class ThreadedHTTPServer(ThreadingMixIn, HTTPServer)`：**必须多线程**。视频流是长连接，单线程会让并发 PROPFIND 全部排队 → 客户端表现为"目录刷不出来"。
- 启动时挂 `self._server.password` 与 `self._server.root_directory` 两个属性给 handler 用。
- 缩略图**复用 PC 端的 `ThumbnailRunnable._generate()`，写同一个 `thumbnails/` 目录** —— PC 端生成过的，共享端直接命中，反之亦然。
- 对外 URL 形态：
  ```
  http(s)://<ip>:<port>/                     浏览器 UI
  http(s)://<ip>:<port>/<虚拟文件名>.mp4      WebDAV 直接取流（VLC / ES / 4XVR 用这个）
  ```

---

## 6. 安全模型

| 面 | 做法 | 代码位置 |
|---|---|---|
| 传输加密 | 自签 TLS（`assets/lockedshare_cert.pem`），TLS≥1.2；证书缺失时**降级为 HTTP 并打印警告** | `network_share_server.start()` |
| WebDAV 认证 | `Basic` / `Bearer` 两种都接受，值为 `base64("user:pass")` | `webdav_server._authenticate()`（第 68 行） |
| 媒体标签认证 | `<video>/<img>` 无法带 header，故额外接受 `?token=base64(user:pass)` | 同上 |
| 口令比较 | `hmac.compare_digest`（防时序侧信道） | 同上 |
| 暴力破解 | 每 IP 60 秒内 5 次失败 → `429 Too Many Requests` | `_failed_attempts` 类属性 |
| 路径穿越 | `realpath` + 根目录包含性判定，拒绝 `..` / 绝对路径 / `C:foo` | `webdav_server._get_local_path()` / `_within_root()`（第 354 行）、`network_share_server._resolve_safe_path()` |
| 本地元数据 | `library.json`、`share_configs.json` 用机器密钥加密；`library.key` 为 32B sidecar | `core/secrets_store.py` |
| 访问日志 | 只记 `sha256(路径)[:12] + 扩展名`，不落真实路径 | `core/access_logger.py` |
| 下载解密 | 密码走 `X-EVF-Password` **请求头**，不放 URL query | `_api_download` |

**已知残留风险（未修，留给后续判断）**：

- 自签证书需要客户端手动信任，"链接不安全"告警是**预期行为**，不是 bug。
- 共享仅靠单一密码，没有 per-user 账号体系（Web 子项目有 JWT 账号，但那是独立体系）。
- `do_OPTIONS` 只声明 `DAV: 1`，未支持 `PROPPATCH / MKCOL / MOVE / COPY`（定位是**只读浏览 + 删除**，够用）。

---

## 7. 极易复发的坑（**改动前必读**）

这一节是血泪合集。每条都真实发生过，且都造成过用户可见的功能损坏。

### 7.1 Python：同类作用域内重复定义函数 = 前一个被静默覆盖

`core/webdav_server.py` 里曾同时存在两份 `_authenticate`（一份 44 行、一份 508 行），后定义的把前面的**完全覆盖**，导致安全加固全部失效、**但没有任何报错**。

> **对策**：改动大段逻辑后，务必 `grep -n "def <name>" <file>` 确认同名函数只有一处。

### 7.2 ★ 虚拟命名必须"列表名 == 可解析名"

`.evf` 对外要虚拟化成原始扩展名。前缀剥离 + 补扩展名的逻辑在**三个地方**各写了一遍，必须语义一致：

| 位置 | 函数 | 用途 |
|---|---|---|
| `webdav_server.py` | `_virtual_name()`（模块级，**统一入口**） | PROPFIND 列表 + `_resolve_virtual_file` 匹配 |
| `network_share_server.py` | `_virtualize_name()` | JSON API 文件列表 |
| `web/services/` | 各自的虚拟化 | Web 子项目 |

历史 bug：

1. `_generate_propfind_xml` 只在"补了扩展名"的分支里更新变量，导致 dedupe 命中时把**磁盘原始名 `video.mp4.evf` 直接写进 href** → 列表泄漏内部命名；
2. `_resolve_virtual_file` **不做 dedupe**，对 `video.mp4.evf` 算出 `video.mp4.mp4`，而列表里写的是 `video.mp4` → **列表里能看见、点开 404（即用户说的"视频打不开"）**。

> **对策**：只保留一个 `_virtual_name()` 实现；且让 `_resolve_virtual_file` **同时接受虚拟名与磁盘原始名**（兼容客户端缓存的旧 URL）。

### 7.3 ★ HTTP Range：必须支持 `bytes=-N` 后缀形式

这是"**视频经常打不开**"的真正根因。

- MP4 若未做 faststart，索引 `moov` 在**文件尾部**。播放器会先发 `Range: bytes=-<N>`（**最后 N 字节**）去取索引。
- 旧代码用 `range_header.split('-')` 解析，缺起始值时**默认填 0**，于是后缀请求被当成前缀请求 → 播放器拿到文件头而不是尾部 → `moov atom not found` → 拒绝播放。
- 这解释了为什么是"**经常**"而不是"总是"：不同播放器/不同探测策略，有的用 `bytes=0-`（能开），有的用 `bytes=-N`（打不开）。

修复：新增 `utils/range_utils.parse_range_header(header, total_size) -> Optional[(start, end)]`，**统一**在 5 处使用：

| 文件 | 位置 | 服务对象 |
|---|---|---|
| `core/webdav_server.py` | `_handle_get_head`（第 254 行） | WebDAV（VR / ES / VLC 走这条） |
| `core/network_share_server.py` | `_serve_file`（第 395 行） | 旧版兼容路由 |
| `core/network_share_server.py` | `_serve_stream`（第 466 行） | 旧版兼容路由 |
| `core/network_share_server.py` | `_api_files_raw`（第 1134 行） | 非加密文件直读 |
| `core/stream_decoder.py` | 第 56 行 | PC 端本地回环播放 |

> `web/services/stream_service.py` 里是**独立实现**（Web 子项目 `sys.path` 根是 `web/`，不方便 import 父级的 `utils`），它**本来就支持**后缀，本次未改。
> **若以后动它，请把三种形式（`bytes=a-b` / `bytes=a-` / `bytes=-n`）都覆盖。**

### 7.4 ★ 目录列举：单个坏条目不能清空整个目录

旧 `_generate_propfind_xml` 把整个 `for entry in scandir(...)` 包在一个 `try/except OSError` 里。任一 `entry.stat()` 抛错（长路径、失效软链、权限）→ **整个目录返回空列表**，客户端表现为"深一点的目录有时候不显示"。

修复后：**逐条目 try/except**，坏条目 `continue`，其余正常输出。

配套（`utils/win_paths.py`）：Windows 全路径 >260 字符时 `scandir/stat/open` 可能抛 `OSError`，尤其在 PyInstaller 冻结程序里（bootloader manifest 未必声明 `longPathAware`，即使注册表 `LongPathsEnabled=1` 也白搭）。因此对这些操作提供 `to_extended()`（加 `\\?\` 前缀）重试封装，并在 `to_extended` 里正确处理 UNC 路径（`\\?\UNC\...`）。

### 7.5 `self.path` 含查询串

`BaseHTTPRequestHandler.path` 是**原始请求路径，带 `?query`**。旧 `_get_local_path` 直接 `unquote` 后拼路径 → `/a.mp4?token=xxx` 被当成文件名 → 必然 404。这会让 `?token=` 认证路径**整体失效**（`<video src>` 就靠它）。

修复：`_get_local_path` 先 `urlparse(path).path` 去掉查询串；PROPFIND 生成 href 时也用去查询串的路径。

### 7.6 SMB 的空实现

`SMBClient.get_file_stream()` 是**空实现**。下载 / raw 类接口必须走 `get_file_object()`，否则 SMB 模式下必挂。

### 7.7 中文 Windows 下的编码

- `.bat` / `.ps1` **必须纯 ASCII**，否则 cmd 里乱码。已踩过：`web/requirements.txt` 曾被追加成 UTF-16LE，`pip install -r` 直接报错（已修为纯 ASCII）。
- `subprocess` 不要用 `text=True`；`whoami` / `icacls` 输出是 ANSI/OEM，改用手动 `mbcs → utf-8 → oem` 顺序解码。
- 本机存在会拦截 `127.0.0.1` 的 HTTP 代理：自测本地服务时 httpx 要 `trust_env=False`，curl 要 `--noproxy '*'`。自测脚本用 `http.client` 直连可完全绕开代理。
- Windows 用 `icacls` 收紧权限**必须带校验+回滚**：用 `USERNAME` 环境变量拼 `user:F` 一旦拼空会写成 `DOMAIN\:(F)`，连自己都读不了该文件。用 `whoami` 拿真实身份，执行后立刻试读写，失败立即 `icacls /reset`。

### 7.8 PyQt6 的两个坑

- `ui/network_share_dialog.py`：`QLineEdit.addAction()` **只接受 QAction/QIcon**，传字符串会 `TypeError`；emoji 图标在源码里还可能被写成 `??`。密码框的"眼睛"按钮因此改为 `QPainter` **手绘 QIcon**。
- `QtWebEngineWidgets` 必须在 `QApplication` **实例化之前**导入（把相关 import 放模块顶层），并 `QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)` 双保险。否则报 `QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts must be set before a QCoreApplication instance is created`。

### 7.9 前端入口拦截（"所有视频都打不开"的第二个来源）

`web/static/js/app.js` 的 `onFileClick` 里曾有一段：遇到**非 `.evf` 的视频**就 `showToast("ℹ️ 非加密视频请下载后播放")` 然后 `return`。
**但浏览器端拿到的本来就是已解密的流**，所以这个判断等于把所有非加密视频全部拦死。

修复：统一改成进 `Player.play(file)`；`player.js` 的非加密分支直接播 `/api/files/raw`。

> **教训**：症状出现在 `player.js`，真凶却在 `app.js` 的入口判断。改播放问题先把 `onFileClick` 整条链路读完。

---

## 8. 自测与验证（**改完必须跑**）

### 8.1 `_dav_selftest.py`

```bash
K:/Python312/python.exe _dav_selftest.py ; echo "exit=$?"
```

它会：

1. 用**项目自己的 `EncryptionEngine`** + 已知口令 `selftest-pw`，把真实样本 `633d42658e7d7e8b643d1e8bbac5ac2b.mp4` 加密成一批 `.evf`，命名刻意覆盖真实库的形态：`IMG_6304.evf`、`video.mp4.evf`（dedupe 用例）、`zzz啥.evf`、`-5263937573636121720 (2).evf`（空格+括号）、中文层级目录，以及一条 **>260 字符**的深路径。
2. 在 `18099` 端口起 `NetworkShareServer`（HTTP，root 指向临时目录 `_davtest/`）。
3. 跑 **31 项断言**：PROPFIND 各层级、深路径、虚拟名解析、三种 Range 形式、`?token=`、路径穿越拦截、web API raw / stream 的后缀 Range。
4. 用 **ffprobe 真实打开**解密流，并**额外用 ffmpeg 造一个 moov 在尾部的 non-faststart MP4** 再验一遍——这就是"视频打不开"的原始场景。

**当前基线：`31/31 passed`**（2026-09-14 实测复核）。改动 Range / 命名 / 路由后如果掉到 31 以下，就是回归。

> 测试会真实加解密并写盘（约几十 MB），跑完自动 stop 服务；`_davtest/` 可随时删除，已在 `.gitignore` 里。

### 8.2 手工冒烟（真机，不可省）

```bash
# 起共享（PC 客户端 → 网络共享 → 设密码 → 启动），然后：
curl -sk -u admin:<pw> -X PROPFIND -H "Depth: 1" https://127.0.0.1:8080/ | head -40

curl -sk -u admin:<pw> -r -1024 -D- -o /dev/null https://127.0.0.1:8080/<虚拟名>.mp4
#   期望：HTTP 206 且 Content-Range 形如  bytes <total-1024>-<total-1>/<total>

ffprobe "https://127.0.0.1:8080/<虚拟名>.mp4?token=$(printf 'admin:<pw>' | base64)"
```

真机客户端另外至少验一遍：**ES 文件浏览器**（进到 3 层以上目录再点视频）、**VLC**、**4XVR**（VR 头显）。

---

## 9. 隐私与仓库卫生

`.gitignore` 已排除（**绝不允许提交**）：

```
# 加密媒体
*.evf  *.enc  *.mp4  *.mkv  *.mov  *.avi  *.ts  *.m4v
# 图片（含用户私人图片）
*.jpg  *.jpeg  *.gif  *.bmp  *.webp  *.png
!assets/placeholder_*.png              # 例外：应用内置占位图必须入库
# 证书与密钥
*.pem  *.key  *.crt  *.p12
# 本地元数据（含真实路径 / 播放历史）
library.json  library.json.bak*  share_configs.json  share_configs.json.bak*
# 日志
access.log  *.log
# 缩略图与运行时数据
thumbnails/  web/data/  web/thumbnails/  web/cache/
# 本地测试残留
123.bat  .verify_reg.json  _davtest/  _davtest_moovend.mp4  _selftest_out.txt
# 工作区记忆（含项目内部信息）
.workbuddy/
# Python / 构建产物 / 编辑器
__pycache__/  *.pyc  venv/  .venv/  .env  build/  dist/  *.spec
web_deploy_package.zip  LockedVideoPlayer.exe  *.exe
.vscode/  .idea/  .DS_Store  Thumbs.db
```

> 上面是**语义摘要**。真实文件见仓库根 `.gitignore`——那里每条 pattern 后面**不能有任何字符**（见 9.1.1）。

### 9.1 GitHub 发布（状态：**未完成**）

- 目标仓库：`git@github.com:Jacky-Yang123/-Locked-File-Manager-Especially-Video-Pic-Player.git`
- SSH 认证已验证通过；远程 `master` 分支是**旧快照**（含 `.pyc`、`123.bat`、`.vscode`），需覆盖。
- **关键约束**：本地 git 历史上存在过明文的 `library.json`（含真实路径）。单纯加 `.gitignore` **不会**清除旧提交里的内容，必须**重建历史**：
  ```bash
  git checkout --orphan clean-main
  git add -A
  git commit -m "Initial commit"
  git branch -M clean-main master
  git push --force origin master
  ```
- 推送前用 `git ls-files` 复查一遍暂存区，确认零隐私文件。

#### 9.1.1 ★★ 血泪教训：`.gitignore` **不支持行尾注释**

**git 只把「以 `#` 开头的整行」当注释。** 写在 pattern 后面的行尾注释会被当成 pattern 的一部分 → 该条规则**静默失效，不报任何错**。

本项目的 `.gitignore` 曾经长这样：

```
library.json          # 播放历史（含路径）
library.key           # 机器加密密钥
thumbnails/           # 缩略图缓存
web/data/             # web 用户数据
```

看起来毫无问题，实际上 `library.json`、`library.key`、`share_configs.json`、`access.log`、`thumbnails/`、`web/data/` 这**六条隐私规则全部没生效**。
如果当时直接 `git add -A && git push`，用户的播放历史（含真实路径）、机器加密密钥、访问日志、加密缩略图缓存、SQLite 数据库会**全部公开到 GitHub**。

**排查方法**（改完 `.gitignore` 必须跑）：

```bash
# 逐条验证是否真的被忽略（-q 静默，退出码 0 = 已忽略）
for f in library.json library.key share_configs.json access.log \
         thumbnails/x.enc web/data/app.db 123.jpg; do
  printf "%-30s " "$f"
  git check-ignore -q "$f" && echo "IGNORED ok" || echo ">>>> NOT IGNORED <<<<"
done

# 反向验证：源码资源不能被误伤
for f in main.py web/app.py assets/placeholder_pdf.png; do
  printf "%-30s " "$f"
  git check-ignore -q "$f" && echo ">>>> WRONGLY IGNORED <<<<" || echo "tracked ok"
done
```

> **规范**：`.gitignore` 里**所有注释必须独占一行**，pattern 后面不许跟任何字符（连空格都不要）。
> 另外 `*.png` 会连应用内置占位图一起忽略，必须用 `!assets/placeholder_*.png` 例外放行（negation 要写在后面，且父目录不能被整体排除）。

---

## 10. 当前状态

### 10.1 本轮已完成

| # | 问题 | 根因 | 修复 |
|---|---|---|---|
| 1 | WebDAV 视频**经常打不开** | Range 解析不支持 `bytes=-N` 后缀 → moov 探测失败 | 新增 `utils/range_utils.py`，统一 5 处调用 |
| 2 | WebDAV 里**深目录不显示** | 单条目 `stat` 抛错清空整个目录；长路径无兜底 | 逐条目容错 + 新增 `utils/win_paths.py` 长路径重试 |
| 3 | 列表泄漏内部名 / 列表名点开 404 | 虚拟命名三处实现不一致、`_resolve_virtual_file` 缺 dedupe | 抽出 `_virtual_name()` 统一；resolver 兼容虚拟名与原始名 |
| 4 | `?token=` 访问必然 404 | `self.path` 带查询串被当文件名 | `_get_local_path` 先剥查询串 |
| 5 | 路径穿越 | `_get_local_path` 无根目录包含性校验 | `realpath` + `_within_root()`；`_resolve_safe_path` 同步加固（分隔符感知） |
| 6 | `web/requirements.txt` 无法 `pip install` | 末尾两行被写成 UTF-16LE | 重写为纯 ASCII |
| 7 | `.gitignore` 六条隐私规则**静默失效** | 用了 git 不支持的**行尾注释**写法 | 重写为「注释独占一行」；`git check-ignore` 逐条验证 17/17 忽略、9/9 保留 |

**验证：`_dav_selftest.py` → 31/31 passed（2026-09-14 实测）**，含 ffprobe 端到端与 moov-at-end 场景。

### 10.2 未做 / 建议下一步

- **ES 文件浏览器 + VR 头显真机复验**：自动化测试已覆盖协议层，但客户端怪癖只能真机确认（尤其 ES 对 `<D:getcontentlength>` 的容错、4XVR 的 seek 行为、中文/空格文件名的 URL 编码）。
- **PyInstaller 长路径**：确认冻结 exe 的 manifest 是否声明 `longPathAware`；若否，`utils/win_paths.py` 的 `\\?\` 兜底就是主力保障。
- **`web/services/stream_service.py` 的 Range 实现**仍是独立副本，建议后续与 `utils/range_utils.py` 语义对齐（需先解决跨子项目 import）。
- **版本号不一致**：`utils/constants.APP_VERSION = "2.0.0"`、根 `README.md` 写的是 v2.0.0，但产品实际已迭代到 v3.5.x 一线。README 内容也还没提 `web/` 子项目、HTTPS 共享、本地路径模式，**建议重写 README**。
- **PC 客户端缺双击启动脚本**：目前只有 `web/run_server.bat`，根目录没有 `start.bat`。用户的硬性偏好是 GUI 桌面项目**必须**附双击即用脚本（内容纯 ASCII），建议补一个。
- **GitHub 发布未完成**：见 9.1。
- **WebDAV 写操作**：目前只有 `DELETE`；`MKCOL / MOVE / COPY / PROPPATCH` 未实现（定位是只读浏览 + 删除）。
- **`/api/unlock` 与 `/api/try_cached`**：共享端遗留的 POST 端点，实际依赖 `StreamingDecryptor` 会话缓存逻辑，重构时注意别把 PC 端播放链路带崩。

---

## 11. 协作约定（用户偏好，请严格遵守）

1. **交付必须端到端真跑通**。不接受"应该可以"、不接受只做静态检查或部分 import 测试。改完代码要在运行中的服务/真机上自测，用 `✓ / ✗ / HTTP 码` 这类可验证信号回话。
2. **不要过度测试**。验证一轮通过即交付，禁止反复跑测试刷时长。
3. **脚本文件（`.bat` / `.ps1`）必须纯 ASCII**，写完用字节检查确认。
4. **GUI 项目必须附双击即用的启动脚本**，不要只给命令行说明。
5. **不要设置人造下限**。UI 设置项（字号、透明度、token/图像上限等）必须给用户完全自由度，禁止硬编码 cap。
6. **内容绝不丢失**是红线：段落要按句子级边界切分，token 估算要贯穿 transcript + prompts + materials，禁止 partial 摘要。
7. **算法类改动前先调研开源方案并汇报等审批**；模型/方案选型由 AI 自己权衡并给出 pros/cons。
8. **遇到网络/下载/连接卡住立即停手**并简短说明卡点，不要自行反复重试。
9. 上线/修复后主动提示用户：**"请到任务管理器确认进程已完全退出再启动"**（否则新功能不生效）。
10. 沟通用**中文**，语气直接，别绕弯、别敷衍。出错时先认错、给证据、给修复。
