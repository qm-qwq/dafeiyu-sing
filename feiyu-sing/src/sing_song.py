# -*- coding: utf-8 -*-
"""唱一首歌（Windows 侧运行）：搜索 → 下载 → 分离(WSL) → RVC 换声 → 混音 → mp3

用法: python sing_song.py "雨爱"
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid

# Windows 控制台默认 GBK，B站标题里有音乐符号会直接崩；强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WSL_VENV = "/root/.local/share/feiyu-voice/cuda/tts/venv"
YTDLP = r"D:\ComfyUI-aki-v2.7z\ComfyUI-aki-v2\python\Scripts\yt-dlp.exe"
FFMPEG = r"D:\shipinmoxing\bin\ffmpeg.exe"
SRV = r"D:\大肥鱼随心所欲\_feiyu_voice\astrbot_plugin_feiyu_voice-main\server"
BASE = "http://127.0.0.1:9880"
WORK_ROOT = r"D:\shipinmoxing\covers"

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Referer": "https://music.163.com/",
}


def log(msg):
    print(f"[sing] {msg}", flush=True)


def http_get(url, timeout=120):
    req = urllib.request.Request(url, headers=UA)
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
    r = urllib.request.Request(BASE + path, data=body, headers=headers)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()


def safe_name(s):
    return re.sub(r"[^\w\u4e00-\u9fff-]+", "_", s)[:40]


def clean_song(song):
    """把「（蝴蝶-洛天依）」「蝴蝶 洛天依」这类写法归一成核心歌名做缓存键"""
    raw = song.strip()
    # 整体被括号包住时，括号里的才是内容
    whole = re.fullmatch(r"[（(【\[](.*?)[）)】\]]", raw)
    s = whole.group(1) if whole else re.sub(r"[（(【\[].*?[）)】\]]", "", raw)
    s = re.split(r"[-–—_/\s]+", s)[0]
    s = s.strip(" 《》【】\"'「」")
    if not s:
        s = re.sub(r"[^\w\u4e00-\u9fff]+", "", raw)
    return s or song


def to_wsl(p):
    return p.replace("D:\\", "/mnt/d/").replace("\\", "/")


BILI_HEADERS = {
    "User-Agent": UA["User-Agent"],
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
}


def bili_cookie():
    """取一个可用 buvid，避免搜索被 412 风控"""
    try:
        req = urllib.request.Request("https://api.bilibili.com/x/frontend/finger/spi",
                                     headers=BILI_HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read()).get("data") or {}
        return f"buvid3={d.get('b_3')}; buvid4={d.get('b_4')}"
    except Exception:
        return ""


def sec_to_len(s):
    try:
        parts = [int(x) for x in str(s).split(":")]
        total = 0
        for p in parts:
            total = total * 60 + p
        return total
    except Exception:
        return 0


def download(song, work):
    log(f"搜索 {song}")
    cookie = bili_cookie()
    headers = dict(BILI_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    kw = urllib.parse.quote(song)
    url = (f"https://api.bilibili.com/x/web-interface/search/type"
           f"?search_type=video&keyword={kw}&page=1")
    data = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read())
            if data.get("code") == 0:
                break
            log(f"搜索返回 {data.get('code')}，重试")
        except Exception as exc:
            log(f"搜索异常 {type(exc).__name__}")
        time.sleep(4)

    items = ((data or {}).get("data") or {}).get("result") or []
    usable = [it for it in items if sec_to_len(it.get("duration")) >= 60]
    if not usable:
        raise RuntimeError(f"没搜到《{song}》的完整音频")
    pick = usable[0]
    bvid = pick.get("bvid")
    title = re.sub(r"</?em[^>]*>", "", pick.get("title", ""))
    log(f"找到: {title} ({bvid}, {pick.get('duration')})")

    out_tpl = os.path.join(work, "raw.%(ext)s")
    for old in ("raw.wav", "raw.mp3", "raw.m4a", "raw.webm", "raw.part", "raw.m4a.part"):
        p = os.path.join(work, old)
        if os.path.exists(p):
            os.remove(p)

    # 走 B站 API 直接拿音频流（绕过 yt-dlp 的网页风控）
    raw = os.path.join(work, "raw.wav")
    try:
        audio_url, best_bw = bili_audio_url(bvid, cookie)
        log(f"拿到音频流（{best_bw//1000}kbps）")
        blob = download_stream(audio_url)
        m4s = os.path.join(work, "raw.m4s")
        with open(m4s, "wb") as f:
            f.write(blob)
        r = subprocess.run(
            [FFMPEG, "-y", "-i", m4s, "-ar", "44100", "-ac", "2", raw],
            capture_output=True, timeout=600,
        )
        if r.returncode != 0 or not os.path.exists(raw):
            raise RuntimeError("m4s 转 wav 失败")
        log(f"下载完成 {os.path.getsize(raw)/1024/1024:.1f}MB")
        return title, raw
    except Exception as exc:
        log(f"API 拿流失败（{exc}），回退 yt-dlp")

    last_err = ""
    for attempt in range(3):
        cookie_arg = ["--add-header", f"Cookie: {cookie}"] if cookie else []
        cmd = [YTDLP, "-f", "bestaudio", "-x", "--audio-format", "wav",
               "--audio-quality", "0", "--ffmpeg-location", os.path.dirname(FFMPEG),
               "--user-agent", UA["User-Agent"],
               "--referer", "https://www.bilibili.com/",
               *cookie_arg, "-o", out_tpl, f"https://www.bilibili.com/video/{bvid}"]
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
        if os.path.exists(raw) and os.path.getsize(raw) > 500_000:
            log(f"下载完成 {os.path.getsize(raw)/1024/1024:.1f}MB")
            return title, raw
        last_err = (r.stderr or b"")[-300:].decode("utf-8", "replace")
        if "412" in last_err or "Precondition" in last_err:
            log(f"被风控，第 {attempt+1} 次重试…")
            time.sleep(6 + attempt * 6)
            cookie = bili_cookie()
        else:
            break
    raise RuntimeError("下载失败: " + last_err)


def bili_audio_url(bvid, cookie):
    """用 view + playurl 接口拿最佳音轨地址"""
    headers = dict(BILI_HEADERS)
    if cookie:
        headers["Cookie"] = cookie

    def get(url):
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read())

    view = get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
    if view.get("code") != 0:
        raise RuntimeError(f"view 失败 {view.get('code')}")
    cid = view["data"]["pages"][0]["cid"]
    q = urllib.parse.urlencode({"bvid": bvid, "cid": cid, "fnval": "16", "fourk": "1"})
    play = get(f"https://api.bilibili.com/x/player/playurl?{q}")
    if play.get("code") != 0:
        raise RuntimeError(f"playurl 失败 {play.get('code')}")
    audios = ((play.get("data") or {}).get("dash") or {}).get("audio") or []
    if not audios:
        raise RuntimeError("没有音频轨")
    best = max(audios, key=lambda x: x.get("bandwidth", 0))
    return best.get("baseUrl") or best.get("base_url"), best.get("bandwidth", 0)


def download_stream(url, referer="https://www.bilibili.com/"):
    headers = {"User-Agent": UA["User-Agent"], "Referer": referer}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def separate(raw, work):
    log("分离人声（WSL demucs）")
    wsl_raw = to_wsl(raw)
    wsl_out = to_wsl(os.path.join(work, "sep"))
    cmd = ["wsl.exe", "-d", "Ubuntu", "-u", "root", "--",
           WSL_VENV + "/bin/python", "-m", "demucs", "-n", "htdemucs",
           "--two-stems=vocals", "-o", wsl_out, wsl_raw]
    r = subprocess.run(cmd, capture_output=True, timeout=3600)
    if r.returncode != 0:
        err = (r.stderr or b"")[-600:].decode("utf-8", "replace")
        raise RuntimeError("separate failed: " + err)
    base = os.path.join(work, "sep", "htdemucs", "raw")
    return os.path.join(base, "vocals.wav"), os.path.join(base, "no_vocals.wav")


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
        raise RuntimeError("convert failed: " + str(st.get("error")))
    out = os.path.join(work, "vocal_feiyu.wav")
    with open(out, "wb") as f:
        f.write(api(f"/v1/jobs/{jid}/audio"))
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
        err = (r.stderr or b"")[-400:].decode("utf-8", "replace")
        raise RuntimeError("mix failed: " + err)
    mp3 = os.path.join(work, f"{name}.mp3")
    subprocess.run([FFMPEG, "-y", "-i", final_wav, "-codec:a", "libmp3lame",
                    "-qscale:a", "2", mp3], capture_output=True, timeout=600)
    return mp3


def main():
    if len(sys.argv) < 2:
        print("usage: sing_song.py 歌名")
        return 2
    song = sys.argv[1].strip()
    name = safe_name(clean_song(song))
    work = os.path.join(WORK_ROOT, "job_" + name)
    os.makedirs(work, exist_ok=True)
    started = time.time()

    def done(mp3, title, how):
        log(f"完成 {time.time()-started:.0f}s（{how}）")
        size = os.path.getsize(mp3) / 1024 / 1024
        print(f"RESULT {mp3} | {title} | {size:.1f}MB | {how}", flush=True)
        return 0

    # ① 之前已经唱完的成品，直接给回去
    final = os.path.join(work, f"大肥鱼唱_{name}.mp3")
    if os.path.exists(final) and os.path.getsize(final) > 300_000:
        log("这首歌之前唱过，直接用本地的")
        return done(final, song, "缓存成品")

    converted = os.path.join(work, "vocal_feiyu.wav")
    inst = os.path.join(work, "sep", "htdemucs", "raw", "no_vocals.wav")
    raw = os.path.join(work, "raw.wav")

    # ② 换完声的人声还在，只差混音
    if os.path.exists(converted) and os.path.exists(inst):
        log("人声和伴奏都在本地，只做混音")
        mp3 = mix(converted, inst, work, "大肥鱼唱_" + name)
        return done(mp3, song, "缓存混音")

    # ③ 原曲还在，跳过搜索下载
    if os.path.exists(raw) and os.path.getsize(raw) > 1_000_000:
        log("原曲在本地，跳过搜索和下载")
        title = song
        vocal, inst = separate(raw, work)
    else:
        title, raw = download(song, work)
        vocal, inst = separate(raw, work)

    converted = convert(vocal, work)
    mp3 = mix(converted, inst, work, "大肥鱼唱_" + name)
    return done(mp3, title, "完整流程")


if __name__ == "__main__":
    sys.exit(main())
