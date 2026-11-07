# -*- coding: utf-8 -*-
"""唱一首歌（Windows 侧）：搜歌 -> 下载 -> 分离(WSL) -> RVC 换声 -> 混音 -> mp3

用法:
    python sing_song.py "歌名"            # 完整翻唱
    python sing_song.py "歌名" --preview  # 只搜索+拿歌词，输出 PREVIEW {...} 供确认
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WSL_VENV = "/root/.local/share/feiyu-voice/cuda/tts/venv"
TTS_PY = "/root/.local/share/feiyu-voice/cuda/tts/venv/bin/python"
FFMPEG = r"D:\shipinmoxing\bin\ffmpeg.exe"
SRV = r"D:\大肥鱼随心所欲\_feiyu_voice\astrbot_plugin_feiyu_voice-main\server"
BASE = "http://127.0.0.1:9880"
WORK_ROOT = r"D:\shipinmoxing\covers"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}

BILI_HEADERS = {
    "User-Agent": UA["User-Agent"],
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
}

BAD_WORDS = (
    "翻唱", "cover", "COVER", "Cover", "DJ", "dj", "合辑", "串烧", "纯音乐",
    "伴奏", "remix", "Remix", "鬼畜", "教程", "钢琴版", "吉他", "指弹", "教学", "切片",
    "音高", "测量", "分析", "反应", "对比", "榜单", "排名", "混剪", "reaction",
    "讲解", "解析", "识别", "扒谱", "听歌识曲", "换声", "变声", "搞笑",
    "技巧", "轻松唱", "如何唱", "练习", "唱好", "声乐", "比赛", "选秀",
    "琴谱", "光遇", "演奏", "谱子", "手碟", "八音盒", "电子琴", "古筝", "二胡",
    "钢琴曲", "吉他谱", "伴奏曲", "卡拉OK", "ktv", "KTV",
    # 现场类混响重，换声容易出电音
    "现场", "Live", "live", "LIVE", "演唱会", "音乐节", "大合唱", "合唱", "饭拍",
    "翻自", "变调", "加速版", "降速版", "八倍速", "慢摇",
)

# 干声/无损类优先，RVC 处理起来干净得多
GOOD_WORDS = ("无损", "Hi-Res", "HiRes", "Hi-res", "录音棚", "录音室", "棚内",
              "清唱", "纯人声", "干声", "母带", "官方", "发烧", "DSD", "试音")


def log(msg):
    try:
        print(f"[sing] {msg}", flush=True)
    except Exception:
        pass


def http_get(url, timeout=120, headers=None):
    req = urllib.request.Request(url, headers=headers or UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def api_key():
    with open(os.path.join(SRV, ".runtime", "voice-service", "api_key.txt")) as f:
        return f.read().strip()


def api(path, data=None, raw=None, timeout=600):
    headers = {"Authorization": "Bearer " + api_key()}
    body = raw
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def safe_name(s):
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", s)[:40]


def clean_song(song):
    """归一化歌名做缓存键。英文不按空格切。"""
    raw = song.strip()
    whole = re.fullmatch(r"[（(【\[](.*?)[）)】\]]", raw)
    s = whole.group(1) if whole else re.sub(r"[（(【\[].*?[）)】\]]", "", raw)
    if re.search(r"[\u4e00-\u9fff]", s):
        s = re.split(r"[-–—_\s/]+", s)[0]
    s = s.strip(" 《》【】\"'「」")
    if not s:
        s = re.sub(r"[^\w\u4e00-\u9fff]+", "", raw)
    return s or song


def flatten(text):
    """去掉所有标点空格，方便做包含匹配"""
    return re.sub(r"[\s《》【】\[\]（）(){}·・\-—_,，.。!！?？:：;；\"'“”‘’「」『』/\\|~～]", "", text).lower()


def sec_to_len(s):
    try:
        parts = [int(x) for x in str(s).split(":")]
        total = 0
        for p in parts:
            total = total * 60 + p
        return total
    except Exception:
        return 0


def bili_cookie():
    try:
        req = urllib.request.Request("https://api.bilibili.com/x/frontend/finger/spi",
                                     headers=BILI_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read()).get("data") or {}
        return f"buvid3={d.get('b_3')}; buvid4={d.get('b_4')}"
    except Exception:
        return ""


def bili_search(keyword, cookie=""):
    """搜 B站，返回时长筛选过的视频（带限流退避）"""
    headers = dict(BILI_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    url = ("https://api.bilibili.com/x/web-interface/search/type"
           f"?search_type=video&keyword={urllib.parse.quote(keyword)}&page=1")
    data = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read())
            if data.get("code") == 0:
                break
            log(f"搜索返回 {data.get('code')}，重试")
            time.sleep(3 * (attempt + 1))
        except urllib.error.HTTPError as exc:
            wait = 4 * (2 ** attempt)
            log(f"B站限流(HTTP {exc.code})，等 {wait} 秒")
            time.sleep(wait)
            cookie = bili_cookie() or cookie
            if cookie:
                headers["Cookie"] = cookie
        except Exception as exc:
            log(f"搜索异常 {type(exc).__name__}")
            time.sleep(3)
    if not data or data.get("code") != 0:
        return []

    items = ((data.get("data") or {}).get("result")) or []
    candidates = []
    for it in items:
        secs = sec_to_len(it.get("duration"))
        if 60 <= secs <= 600:
            candidates.append((secs, it))
    candidates.sort(key=lambda x: abs(x[0] - 240))
    return [it for _, it in candidates]


def bili_audio_url(bvid, cookie):
    """view + playurl 拿最佳音轨地址"""
    headers = dict(BILI_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    def get(u):
        req = urllib.request.Request(u, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())

    view = get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if view.get("code") != 0:
        raise RuntimeError(f"view failed {view.get('code')}")
    cid = view["data"]["pages"][0]["cid"]
    q = urllib.parse.urlencode({"bvid": bvid, "cid": cid, "fnval": "16", "fourk": "1"})
    play = get(f"https://api.bilibili.com/x/player/playurl?{q}")
    if play.get("code") != 0:
        raise RuntimeError(f"playurl failed {play.get('code')}")
    audios = ((play.get("data") or {}).get("dash") or {}).get("audio") or []
    if not audios:
        raise RuntimeError("no audio track")
    best = max(audios, key=lambda x: x.get("bandwidth", 0))
    return best.get("baseUrl") or best.get("base_url"), best.get("bandwidth", 0)


def download_stream(url):
    headers = {"User-Agent": UA["User-Agent"], "Referer": "https://www.bilibili.com/"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def qq_search(text, limit=6):
    """QQ音乐搜索（主源）：[(歌名, 歌手, 时长秒, mid)]"""
    headers = {"User-Agent": UA["User-Agent"], "Referer": "https://y.qq.com/"}
    url = ("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?w="
           + urllib.parse.quote(text) + f"&format=json&n={limit}&p=1")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
        if txt.startswith("callback("):
            txt = txt[len("callback("):].rstrip(");")
        data = json.loads(txt)
    except Exception as exc:
        log(f"QQ音乐搜索失败 {type(exc).__name__}")
        return []
    songs = ((data.get("data") or {}).get("song") or {}).get("list") or []
    out = []
    for s in songs:
        artist = ", ".join(x.get("name", "") for x in s.get("singer", []))
        out.append((s.get("songname", ""), artist, int(s.get("interval") or 0), s.get("songmid")))
    return out


def netease_search(text, by_lyric=False):
    """网易云搜索（备用 / 歌词反查）"""
    headers = {"User-Agent": UA["User-Agent"], "Referer": "https://music.163.com/"}
    kind = 1006 if by_lyric else 1
    url = ("https://music.163.com/api/search/get/web?s="
           + urllib.parse.quote(text) + f"&type={kind}&limit=8&offset=0")
    data = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read())
            if data.get("result"):
                break
            if data.get("code") == 405:
                log("网易云限流，等 5 秒")
                time.sleep(5)
                continue
            break
        except Exception as exc:
            log(f"网易云搜索失败 {type(exc).__name__}")
            time.sleep(3)
    if not data:
        return []
    songs = (data.get("result") or {}).get("songs") or []
    out = []
    for s in songs:
        artist = ", ".join(a["name"] for a in s.get("artists", []))
        secs = int((s.get("duration") or 0) / 1000)
        out.append((s.get("name", ""), artist, secs, s.get("id")))
    return out


def get_lyric(song_mid, max_lines=4):
    """QQ音乐拿歌词，去掉时间轴/制作人员/广告"""
    headers = {"User-Agent": UA["User-Agent"], "Referer": "https://y.qq.com/portal/player.html"}
    url = ("https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?"
           f"songmid={song_mid}&format=json&nobase64=1")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as r:
            txt = r.read().decode("utf-8", "replace")
        if txt.strip().startswith("MusicJsonCallback("):
            txt = txt.strip()[len("MusicJsonCallback("):].rstrip(");")
        data = json.loads(txt)
    except Exception as exc:
        log(f"歌词获取失败 {type(exc).__name__}")
        return []
    raw = data.get("lyric") or ""
    meta_words = ("作词", "作曲", "编曲", "制作", "混音", "母带", "词", "曲", "吉他",
                  "和声", "监制", "出品", "发行", "录音", "统筹", "企划", "未经", "本歌曲")
    out = []
    for line in raw.split("\n"):
        line = re.sub(r"^\[[^\]]*\]", "", line).strip()
        if not line or len(line) < 4:
            continue
        if line.startswith(meta_words):
            continue
        if re.match(r"^[^:：]{1,6}[:：]", line):
            continue
        if " - " in line and len(line) <= 40:
            continue
        if re.search(r"(未经|许可|不得|翻唱、翻录|版权|授权|听歌就在|星曜计划|酷狗|网易云)", line):
            continue
        if re.search(r"[『』*★☆]", line):
            continue
        if re.search(r"[:：]", line) and len(re.split(r"[:：]", line)[0]) <= 14:
            continue
        if re.search(r"[（(\[【]", line) and len(line) <= 50:
            continue
        line = re.sub(r"[（(\[][^）)\]】]*[）)\]】]", "", line).strip()
        if len(line) < 4:
            continue
        out.append(line)
    return out[:max_lines]


def pick_lyric_snippet(song):
    """挑两句歌词用来跟用户确认"""
    for name, artist, _secs, mid in qq_search(song, limit=3):
        if not mid:
            continue
        lines = get_lyric(mid, 6)
        good = [l for l in lines if len(l) >= 5]
        if len(good) >= 2:
            return " / ".join(good[:2])
        if len(lines) >= 2:
            return " / ".join(lines[:2])
    return ""


def score_candidate(video, song_name, artist, want_secs=0):
    title = re.sub(r"</?em[^>]*>", "", video.get("title", ""))
    flat = flatten(title)
    name_key = flatten(song_name)
    score = 30 if (not name_key or name_key in flat) else -50
    for a in re.split(r"[,，、/&]", artist or ""):
        a = a.strip()
        if a and flatten(a) in flat:
            score += 40
            break
    for bad in BAD_WORDS:
        if bad in title:
            score -= 60
            break
    for good in GOOD_WORDS:
        if good in title:
            score += 25          # 干声/无损版本优先，换声更干净
            break
    secs = sec_to_len(video.get("duration"))
    if want_secs:
        if abs(secs - want_secs) <= 20:
            score += 25
        elif abs(secs - want_secs) <= 60:
            score += 10
        elif abs(secs - want_secs) >= 120:
            score -= 25
    score += max(0, 20 - abs(secs - 240) / 20)
    return score


def pick_best_video(videos, song_name, artist, want_secs=0):
    scored = [(score_candidate(v, song_name, artist, want_secs), v) for v in videos]
    scored.sort(key=lambda x: -x[0])
    return scored


def resolve_song(song, cookie):
    """歌名 -> B站视频。优先找干声/清唱版，其次 B站直搜，最后音乐库兜底。"""
    picks = []
    seen = set()

    # ① 先专门找干声版（清唱/纯人声），RVC 处理这种最干净，几乎不出电音
    for dry_kw in (f"{song} 清唱", f"{song} 纯人声", f"{song} 干声"):
        vids = bili_search(dry_kw, cookie)
        if not vids:
            continue
        scored = pick_best_video(vids, song, "", 0)
        # 标题里必须真的带清唱/纯人声这类词，否则不算命中
        for sc, v in scored[:2]:
            t = v.get("title", "")
            if any(k in t for k in ("清唱", "纯人声", "干声", "无伴奏", "伴奏已去除")):
                log(f"  找到干声版: {re.sub(r'</?em[^>]*>', '', t)[:45]}")
                return v, song, ""
        break

    # ② B站 直接搜
    direct = bili_search(song, cookie)
    if direct:
        scored = pick_best_video(direct, song, "", 0)
        if scored:
            top = scored[0][0]
            log(f"  B站直搜 {len(direct)} 条，最优 {top:.0f} 分")
            for sc, v in scored[:3]:
                picks.append((sc, v, song, ""))
            if top >= 60:
                t = re.sub(r"</?em[^>]*>", "", scored[0][1].get("title", ""))
                log(f"  选中(B站直搜): {t}（{top:.0f} 分）")
                return scored[0][1], song, ""

    is_lyric_like = len(song) >= 8 or (" " in song.strip()) or ("，" in song) or ("。" in song)
    cands = qq_search(song)
    src = "QQ音乐"
    if not cands:
        cands = netease_search(song, by_lyric=is_lyric_like)
        src = "网易云"
    if not cands and is_lyric_like:
        cands = netease_search(song, by_lyric=True)
        src = "网易云歌词"
    if cands:
        log(f"  {src} 给出 {len(cands)} 个候选")
        for rank, (name, artist, secs, _sid) in enumerate(cands[:5]):
            if not name:
                continue
            key = (name, artist)
            if key in seen:
                continue
            seen.add(key)
            bonus = max(0, 30 - rank * 8)
            vids = bili_search(f"{name} {artist}".strip(), cookie) or bili_search(name, cookie)
            if not vids:
                continue
            for sc, v in pick_best_video(vids, name, artist, secs)[:2]:
                picks.append((sc + bonus, v, name, artist))
    else:
        log("  音乐库没返回，只用 B站 结果")

    if not picks:
        return None
    picks.sort(key=lambda x: -x[0])
    best_score, best_video, name, artist = picks[0]
    log(f"  共 {len(picks)} 个候选，最优 {best_score:.0f} 分")
    for sc, v, n, a in picks[:3]:
        t = re.sub(r"</?em[^>]*>", "", v.get("title", ""))
        log(f"    {sc:.0f}分 《{n}》{('- ' + a) if a else ''} | {t[:35]}")
    return best_video, name, artist


def download(song, work, preview=False):
    log(f"搜索 {song}")
    cookie = bili_cookie()

    resolved = resolve_song(song, cookie)
    if not resolved:
        raise RuntimeError(f"没搜到《{song}》")
    pick, matched_name, matched_artist = resolved
    bvid = pick.get("bvid")
    title = re.sub(r"</?em[^>]*>", "", pick.get("title", ""))
    log(f"找到: {title} ({bvid}, {pick.get('duration')})")

    # 把这次搜索的结果记下来，下次本地有原曲时可以直接用
    try:
        with open(os.path.join(work, "search_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"title": title, "bvid": bvid, "duration": pick.get("duration"),
                       "song": song}, f, ensure_ascii=False)
    except Exception:
        pass

    for old in ("raw.wav", "raw.mp3", "raw.m4a", "raw.webm", "raw.m4s"):
        p = os.path.join(work, old)
        if os.path.exists(p):
            os.remove(p)

    raw = os.path.join(work, "raw.wav")

    if preview:
        lyric = pick_lyric_snippet(song)
        if not lyric:
            for pat in (r"[\u201c\u201d]([^\u201c\u201d]{6,40})[\u201c\u201d]",
                        r"[\u300c\u300d]([^\u300c\u300d]{6,40})[\u300c\u300d]"):
                mm = re.search(pat, title)
                if mm:
                    lyric = mm.group(1).strip()
                    break
        meta = {
            "title": title,
            "bvid": bvid,
            "duration": pick.get("duration"),
            "lyric": lyric,
            "name": safe_name(clean_song(song)),
            "cached": False,
        }
        try:
            audio_url, _bw = bili_audio_url(bvid, cookie)
            blob = download_stream(audio_url)
            m4s = os.path.join(work, "raw.m4s")
            with open(m4s, "wb") as f:
                f.write(blob)
            subprocess.run([FFMPEG, "-y", "-i", m4s, "-ar", "44100", "-ac", "2", raw],
                           capture_output=True, timeout=600)
            meta["downloaded"] = os.path.exists(raw)
        except Exception as exc:
            log(f"预下载失败: {exc}")
            meta["downloaded"] = False
        return title, None, meta

    for api_try in range(3):
        try:
            audio_url, bw = bili_audio_url(bvid, cookie)
            log(f"音频流 {bw // 1000}kbps（第 {api_try + 1} 次）")
            blob = download_stream(audio_url)
            m4s = os.path.join(work, "raw.m4s")
            with open(m4s, "wb") as f:
                f.write(blob)
            r = subprocess.run([FFMPEG, "-y", "-i", m4s, "-ar", "44100", "-ac", "2", raw],
                               capture_output=True, timeout=600)
            if r.returncode != 0 or not os.path.exists(raw):
                raise RuntimeError("m4s 转 wav 失败")
            log(f"下载完成 {os.path.getsize(raw)/1024/1024:.1f}MB")
            return title, raw, None
        except Exception as exc:
            log(f"下载失败（{exc}），第 {api_try + 1} 次")
            time.sleep(3)
            cookie = bili_cookie() or cookie
    raise RuntimeError("音频下载失败")


def to_wsl(p):
    return p.replace("D:\\", "/mnt/d/").replace("\\", "/")


def separate(raw, work):
    wsl_raw = to_wsl(raw)
    wsl_out = to_wsl(os.path.join(work, "sep"))
    base = ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--",
            TTS_PY, "-m", "demucs", "-n", "htdemucs", "--two-stems=vocals"]
    expect = os.path.join(work, "sep", "htdemucs", "raw")

    for device in (None, "cpu"):
        log("分离人声（%s）" % ("GPU" if not device else "CPU"))
        cmd = base + (["-d", "cpu"] if device else []) + ["-o", wsl_out, wsl_raw]
        r = subprocess.run(cmd, capture_output=True, timeout=5400)
        if r.returncode == 0 and os.path.exists(os.path.join(expect, "vocals.wav")):
            return (os.path.join(expect, "vocals.wav"),
                    os.path.join(expect, "no_vocals.wav"))
        err = (r.stderr or b"")[-400:].decode("utf-8", "replace")
        if device is None and ("out of memory" in err.lower() or "CUDA" in err):
            log("显存不够（可能开着 ComfyUI），改用 CPU 分离")
            import shutil
            shutil.rmtree(os.path.join(work, "sep"), ignore_errors=True)
            continue
        raise RuntimeError("separate failed: " + err)
    raise RuntimeError("分离失败")


def dereverb(vocal, work):
    """去掉人声里的混响（RVC 处理干声才不容易出电音）"""
    log("去混响（DeReverb）")
    outdir = os.path.join(work, "dereverb")
    os.makedirs(outdir, exist_ok=True)
    wsl_in = to_wsl(vocal)
    wsl_out = to_wsl(outdir)
    cmd = ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--", TTS_PY,
           "/mnt/d/shipinmoxing/feiyu_src/dereverb_worker.py", wsl_in, wsl_out]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    text = (r.stdout or b"").decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("PICK "):
            picked = line[5:].strip()
            win = picked.replace("/mnt/d/", "D:\\").replace("/", "\\")
            if os.path.exists(win):
                log(f"  干声: {os.path.basename(win)}")
                return win
    err = (r.stderr or b"")[-300:].decode("utf-8", "replace")
    log(f"去混响失败，用原人声: {err[:150]}")
    return vocal


def convert(vocal, work):
    log("换声（RVC）")
    boundary = uuid.uuid4().hex
    with open(vocal, "rb") as f:
        payload = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="vocals.wav"\r\n',
        b"Content-Type: audio/wav\r\n\r\n",
        payload,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    up = urllib.request.Request(
        BASE + "/v1/assets", data=body,
        headers={"Authorization": "Bearer " + api_key(),
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(up, timeout=900) as resp:
        asset = json.loads(resp.read())
    audio_id = asset.get("id") or asset.get("asset_id")

    job = json.loads(api("/v1/voice-conversion", {"voice": "feiyu", "audio_id": audio_id}))
    jid = job.get("id") or job.get("job_id")
    st = {}
    for i in range(400):
        time.sleep(5)
        st = json.loads(api(f"/v1/jobs/{jid}"))
        if st.get("status") in ("success", "failed"):
            break
        if i % 12 == 0:
            log(f"  转换中 {st.get('status')}")
    if st.get("status") != "success":
        raise RuntimeError("换声失败: " + str(st.get("error")))
    raw_out = os.path.join(work, "vocal_feiyu_raw.wav")
    with open(raw_out, "wb") as f:
        f.write(api(f"/v1/jobs/{jid}/audio"))

    # RVC 输出 40kHz 单声道，统一重采样到 44.1k 立体声，
    # 顺便高通滤掉换声带出来的低频噪音（不去静音，否则会和伴奏错位）
    out = os.path.join(work, "vocal_feiyu.wav")
    cmd = [FFMPEG, "-y", "-i", raw_out,
           "-af", "highpass=f=45,aresample=44100",
           "-ar", "44100", "-ac", "2", out]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out):
        log("后处理失败，用原始输出")
        return raw_out
    return out


def mix(vocal, inst, work, name):
    log("混音")
    final_wav = os.path.join(work, "final.wav")
    cmd = [FFMPEG, "-y", "-i", vocal, "-i", inst,
           "-filter_complex",
           "[0:a]volume=1.0[v];[1:a]volume=0.55[b];[v][b]amix=inputs=2:duration=longest:normalize=0[out]",
           "-map", "[out]", "-ar", "44100", "-ac", "2", final_wav]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("混音失败: " + (r.stderr or b"")[-300:].decode("utf-8", "replace"))
    mp3 = os.path.join(work, f"{name}.mp3")
    subprocess.run([FFMPEG, "-y", "-i", final_wav, "-codec:a", "libmp3lame",
                    "-qscale:a", "2", mp3], capture_output=True, timeout=600)
    return mp3


def main():
    argv = sys.argv[1:]
    preview = "--preview" in argv
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print("usage: sing_song.py 歌名 [--preview]")
        return 2
    song = args[0].strip()
    name = safe_name(clean_song(song))
    work = os.path.join(WORK_ROOT, "job_" + name)
    os.makedirs(work, exist_ok=True)
    started = time.time()

    def done(mp3, title, how):
        log(f"完成 {time.time() - started:.0f}s（{how}）")
        size = os.path.getsize(mp3) / 1024 / 1024
        print(f"RESULT {mp3} | {title} | {size:.1f}MB | {how}", flush=True)
        return 0

    # 不再复用旧成品/旧换声结果：之前搜错过，缓存会把错的反复发出来。
    # 每次重新换声（分离也重做），只有原曲可以复用。
    converted = os.path.join(work, "vocal_feiyu.wav")
    inst = os.path.join(work, "sep", "htdemucs", "raw", "no_vocals.wav")
    raw = os.path.join(work, "raw.wav")

    if os.path.exists(raw) and os.path.getsize(raw) > 1_000_000:
        log("原曲在本地，跳过下载（换声重做）")
        title = song
        dur = ""
        try:
            with open(os.path.join(work, "search_meta.json"), encoding="utf-8") as f:
                prev = json.load(f)
            title = prev.get("title") or song
            dur = prev.get("duration") or ""
        except Exception:
            pass
        if preview:
            lyric = pick_lyric_snippet(song)
            print("PREVIEW " + json.dumps(
                {"title": title, "name": name, "cached": False, "duration": dur,
                 "lyric": lyric, "downloaded": True}, ensure_ascii=False), flush=True)
            return 0
        vocal, inst = separate(raw, work)
    else:
        title, raw, meta = download(song, work, preview=preview)
        if preview:
            print("PREVIEW " + json.dumps(meta, ensure_ascii=False), flush=True)
            return 0
        vocal, inst = separate(raw, work)

    # 去混响实测没改善电音（问题在模型音域，不在混响），默认关掉省 3 分钟
    # 需要时加 --dereverb 参数手动开
    if "--dereverb" in sys.argv:
        vocal = dereverb(vocal, work)
    converted = convert(vocal, work)
    mp3 = mix(converted, inst, work, "大肥鱼唱_" + name)
    return done(mp3, title, "完整流程")


if __name__ == "__main__":
    sys.exit(main())
