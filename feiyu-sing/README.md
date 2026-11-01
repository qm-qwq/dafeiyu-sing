# 肥鱼整歌翻唱 · Feiyu Cover

> 一句话：**说「唱首雨爱」，她就自己去找原曲、拆人声、换成自己的音色、唱完发给你。**

这是给 [astrbot_plugin_feiyu_voice](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice) 补上「整首歌翻唱」能力的扩展。

原项目只有「按谱唱歌」（要 MIDI 谱）和「单段换声」。本仓把它补成**自然语言点歌**：不用谱子、不用附件，说歌名就行。

---

## 效果

QQ 里发一句：

```
大肥鱼唱首雨爱
```

她回「《雨爱》呀，好，我去找找原曲，学一会儿再唱给你听～」，
两分钟后，整首歌按 58 秒切成 5 段语音发过来——**用的是她自己的音色**。

```
歌名
 → B站搜完整原曲（API 拿音频流，不用 yt-dlp）
 → demucs 分离人声/伴奏
 → RVC 换成目标音色
 → ffmpeg 混回伴奏
 → 切 58 秒 → 分段发 QQ
```

---

## 为什么不用 yt-dlp 下载

试过，**IP 级 412 风控**，下几首之后整个 B站都抓不动了。

改成直接调用 B 站播放接口：

```
GET api.bilibili.com/x/web-interface/view?bvid=xxx        → cid
GET api.bilibili.com/x/player/playurl?bvid=xxx&cid=xxx
                                                          → dash.audio[].baseUrl
```

走 API 通道，跟网页风控是两套系统。只带一个 `buvid3` cookie 就够。

---

## 为什么 RVC 调 index_rate

`index_rate` 决定「往目标音色压多狠」：

| 值 | 听感 |
|---|---|
| 0.3（默认） | 还是像原唱，只是嗓子糊了点 |
| **0.7（推荐）** | 明显像目标角色，咬字仍然清楚 |
| 0.9+ | 音色最像，但咬字开始糊 |

本仓默认 **0.7**。

> 注意：RVC 是**音色转换**，保留原唱的呼吸、颤音、拖长、咬字节奏。所以听起来一定像原唱在唱——因为那就是原唱在唱，只是换了嗓子。想让她「自己唱」需要 SVS（歌声合成），那是另一条路。

---

## 依赖

| 组件 | 用途 | 说明 |
|---|---|---|
| [astrbot_plugin_feiyu_voice](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice) | TTS + RVC 服务 + 插件骨架 | **本仓不含它的代码**，另装 |
| 肥鱼音色模型 | CosyVoice3 + RVC v1 | 原作者从 B站 UP 主 **星落落_oi** 授权训练，见原项目 COPYRIGHT |
| [demucs](https://github.com/facebookresearch/demucs) | 人声/伴奏分离 | `pip install demucs`，模型 ~300MB |
| ffmpeg | 转码/混音/切段 | 需要 **支持 libmp3lame** 的构建 |
| Python | 跑脚本 | 建议 3.10+ |

---

## 安装

### 1. 先把原项目跑起来

按 [astrbot_plugin_feiyu_voice 的文档](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice) 部署声音服务（默认 `127.0.0.1:9880`），确认：

```bash
curl -H "Authorization: Bearer <你的key>" http://127.0.0.1:9880/v1/capabilities
```

`tts` 和 `rvc` 都是 `available: true` 再继续。

### 2. 装 demucs

```bash
pip install demucs
```

### 3. 放脚本

把 `src/sing_song.py` 放到任意位置，改开头几个常量：

```python
FFMPEG   = r"D:\你的路径\bin\ffmpeg.exe"
SRV      = r"D:\你的路径\astrbot_plugin_feiyu_voice-main\server"
BASE     = "http://127.0.0.1:9880"
WORK_ROOT = r"D:\你的路径\covers"          # 缓存目录
WSL_VENV  = "/root/.../venv"               # demucs 装在 WSL 时用
```

> 如果 demucs 装在 Windows 本机，把 `separate()` 里的 `wsl.exe -d Ubuntu -u root --` 去掉即可。

### 4. 接进插件

本仓 `patch/main.py.modified` 是改好的插件 `main.py`，做了这些改动：

- 自然语言触发：`大肥鱼说 xxx` / `唱首xxx` / `大肥鱼唱（歌名-歌手）`
- 唱歌任务后台跑，完成后**切 58 秒分段发语音**
- 三级缓存（成品 / 换声后 / 原曲）
- 歌名归一化（`（蝴蝶-洛天依）` 和 `蝴蝶 洛天依` 用同一个缓存）
- 报错全部翻译成角色口吻，不暴露英文堆栈

直接覆盖 `astrbot_plugin_feiyu_voice/main.py`，或者对照着改。

### 5. 把 ffmpeg 加进 PATH

插件发语音前要调 ffmpeg 转格式，PATH 里没有就会「唱砸了」：

```powershell
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";D:\你的路径\bin", "User")
```

改完**重启 AstrBot**。

---

## 缓存机制

| 缓存层 | 命中条件 | 耗时 |
|---|---|---|
| 成品 | 之前完整唱过 | **秒回** |
| 混音 | 换声结果还在，只差混音 | 十几秒 |
| 原曲 | 下载过，跳过搜索和下载 | 一分钟 |
| 无 | 新歌 | 一到两分钟 |

---

## 踩过的坑

写在这里，省得你也踩一遍。

### 1. B站搜索 412

搜索接口也要 cookie。先拿一个：

```python
GET api.bilibili.com/x/frontend/finger/spi   → data.b_3 / data.b_4
Cookie: buvid3=<b_3>; buvid4=<b_4>
```

### 2. 网易云 / 公开音源只有 30 秒试听

`music.163.com/song/media/outer/url`、`api.injahow.cn/meting` 这些走一圈，拿到的都是试听片段。**放弃，直接走 B站。**

### 3. WSL 里的 127.0.0.1 不是 Windows

如果整个脚本跑在 WSL 里，它连不到 Windows 上的 `127.0.0.1:9880`。
**整条流程放 Windows，只把 demucs 交给 WSL。**

### 4. `subprocess(text=True)` 在 Windows 会 GBK 崩

崩了之后 `r.stderr` 变成 `None`，真正的错误被吞掉，你看到的是一个无关的 `TypeError`。

```python
# 别这样
r = subprocess.run(cmd, capture_output=True, text=True)
raise RuntimeError(r.stderr[-400:])   # ← stderr 是 None

# 这样
r = subprocess.run(cmd, capture_output=True)
raise RuntimeError((r.stderr or b"")[-400:].decode("utf-8", "replace"))
```

### 5. B站标题里有花体字，`print` 会崩

`【𝐇𝐢-𝐑𝐞𝐬无损音质】` 这种字符在 GBK 控制台打不出来：

```python
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
```

### 6. 改 RVC 包里的 manifest.json 会破坏完整性校验

改完 `inference.index_rate` 之后，必须同步更新 `files_sha256.json` 里 `manifest.json` 的哈希，否则包校验直接失败。

### 7. QQ 语音 60 秒限制

用 ffmpeg 切 58 秒：

```bash
ffmpeg -y -i in.mp3 -f segment -segment_time 58 \
       -reset_timestamps 1 -c:a libmp3lame -qscale:a 4 out_%03d.mp3
```

**必须重编码**（不能 `-c copy`），否则切点落在 mp3 帧边界上，会切出 5 秒碎片。

---

## 许可

本仓原创代码（`src/`、`patch/`）按 **MIT** 发布。

**不包含**：肥鱼音色模型、原项目代码、第三方运行时。
音色模型的分发条款见 [astrbot_plugin_feiyu_voice 的 NOTICE.md](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice)，原始音频素材来自 B站 UP 主 **星落落_oi**，已获授权用于声库训练。

翻唱成品涉及原曲版权，仅供个人使用。

---

## 致谢

- [Esmerubphire/astrbot_plugin_feiyu_voice](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice) — 肥鱼 TTS/RVC 服务与插件骨架
- [facebookresearch/demucs](https://github.com/facebookresearch/demucs) — 人声分离
- B站 UP 主 **星落落_oi** — 肥鱼音色素材
