# 肥鱼整歌翻唱 · Feiyu Cover

> 一句话：**说「唱首雨爱」，她就自己去找原曲、拆人声、换成自己的音色、唱完发给你。**

这是给 [astrbot_plugin_feiyu_voice](https://github.com/Esmerubphire/astrbot_plugin_feiyu_voice) 补上「整首歌翻唱」能力的扩展。

原项目只有「按谱唱歌」（要 MIDI 谱）和「单段换声」。本仓把它补成**自然语言点歌**：不用谱子、不用附件，说歌名就行。

> **2026-11-07 更新**：加了「先确认再唱」流程、清唱版优先搜索、f0 算法换 fcpe、可选去混响、取消缓存。下面第 4 节是这次的改动说明。

---

## 效果

QQ 里发一句：

```
大肥鱼唱首雨爱
```

她会先回一句 **「等我找找看是哪首～」**，然后：

```
找到的是这首：
【Hi-Res 无损】杨丞琳《雨爱》
（4:22）

歌词：「窗外的天气 / 就像是 你多变的表情」

是这首吗？回「是」我就唱
```

你回「是」，她才开始跑，两分钟后整首歌按 58 秒切成几段语音发过来——**用的是她自己的音色**。

```
歌名
 → 先找 B站 有没有「清唱/纯人声」版（干声，换声最干净）
 → 没有就搜普通版本，按标题/歌手/时长打分选最像原唱的
 → 从 B站 播放接口拿音频流（不用 yt-dlp，绕过网页风控）
 → demucs 分离人声/伴奏
 →（可选）DeReverb 去混响
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

## 缓存

> **2026-11-07 起默认关闭成品缓存**：因为搜索可能挑错，缓存会把错的反复发出来。现在每次都重新搜、重新分离、重新换声，只有原曲文件会复用（省下载）。

| 缓存层 | 现状 |
|---|---|
| 成品 / 换声结果 | ❌ 不使用（每次重做） |
| 原曲 wav | ✅ 复用（省一次下载） |

一首歌的耗时（4 分钟的歌）：分离 10 秒（GPU） + 换声 60 秒 + 混音 5 秒 ≈ **1.5 分钟**。
如果开着 ComfyUI 抢显存，demucs 会降级到 CPU，变成 **5~6 分钟**。

---

## 2026-11-07 这次改了什么

### 1. 先确认再唱

之前是「说完歌名直接开唱」，搜错了只能重来。现在是：

```
你：大肥鱼唱后来
她：等我找找看是哪首～

    找到的是这首：
    《后来》- 刘若英 [无损音质]"后来我总算学会了…"
    （5:33）

    歌词：「后来我总算学会了 / 可惜你 早已远去」

    是这首吗？回「是」我就唱

你：是
她：好，我这就唱～
```

- 回「是/对/嗯/好/唱吧/就这个」→ 开唱
- 回「不是/不对/换/算了」→ 「好吧，那换一首～」
- 5 分钟没回 → 自动作废，不会突然唱起来

### 2. 歌词是真的了

之前从 B站 标题里抠引号内容，经常抠到 UP 主的文案。现在走 **QQ 音乐歌词接口**：

```
歌名 → QQ音乐搜 songmid → 歌词接口 → 去掉时间轴/制作人员/广告 → 取前两句
```

过滤掉：`[ti:]` `[ar:]`、`作词/作曲/编曲`、`Vocal edite：xxx`、`未经许可不得翻唱`、`听歌就在酷狗`、带括号的注解行。

### 3. 清唱版优先

RVC 处理干声最干净。所以搜歌时会先试：

```
{歌名} 清唱 / 纯人声 / 干声
```

标题里真的带这些词才采用，否则回退到普通搜索。

实测：孤勇者、后来都能找到纯人声版；雨爱找不到。

### 4. f0 算法换 fcpe

`rmvpe` 在转音、颤音处会抽风，那一下音高判错就是「电音」。换 **fcpe** 后，静音断点从 59 降到 31（原唱本身 17）。

```json
"f0_method": "fcpe",
"index_rate": 0.42,
"protect": 0.5,
"volume_envelope": 0
```

> Applio 支持的 f0：`crepe` / `rmvpe` / `fcpe` / `hybrid[...]`。**没有 harvest**。
> `hybrid[rmvpe+fcpe]` 在这个版本有 bug（`UnboundLocalError: f0`），别用。

### 5. 可选去混响

B站 上很多歌是带混响的唱片版，RVC 会把混响尾巴当音高转换。可以加 DeReverb：

```bash
python sing_song.py "雨爱" --dereverb
```

**实测对电音改善有限**（问题在模型音域，不在混响），默认关闭省 3 分钟。

装法见 `src/dereverb_worker.py` 头部注释，要点：
- `pip install audio-separator==0.28.2`（新版强制 numpy≥2，会破坏原有环境）
- 模型从 `hf-mirror.com/Blane187/all_public_uvr_models` 下 `UVR-DeEcho-DeReverb.pth`（213MB）
- 放 `~/.local/share/feiyu-voice/models/`，配 `vr_model_data.json`（补模型 md5 条目）
- **必须 `CUDA_VISIBLE_DEVICES=""` 强制 CPU**（5060 的 sm_120 下 cudnn 算子没 kernel）

---

## 已知限制：副歌高音区有电音

这不是参数问题，是 **RVC 模型的能力上限**。

排查过程（都试过）：

| 尝试 | 结果 |
|---|---|
| f0 rmvpe → fcpe | 断点 59 → 31，电音还在 |
| index_rate 0.7 → 0.42 | 音色变淡，电音还在 |
| protect 0.33 → 0.5 | 帮助很小 |
| volume_envelope 关掉 | 音量不抖了，电音还在 |
| 去混响 | 混响洗干净了，电音还在 |
| 重采样 + 高通 | 音质干净，电音还在 |

**根本解法**：重新训练 RVC 模型（需要该角色 30 分钟以上的干净干声，最好带高音段）。

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
