# -*- coding: utf-8 -*-
"""去混响 worker（WSL 侧）：python dereverb_worker.py <input.wav> <outdir>
成功时打印 PICK <干声路径>
"""
import os
import sys

# 5060 的 sm_120 下部分 cudnn 算子没 kernel，强制 CPU
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["OMP_NUM_THREADS"] = "4"

MODEL_DIR = "/root/.local/share/feiyu-voice/models"
MODEL_NAME = "UVR-DeEcho-DeReverb.pth"


def main():
    if len(sys.argv) < 3:
        print("usage: dereverb_worker.py <input.wav> <outdir>")
        return 2
    src, outdir = sys.argv[1], sys.argv[2]
    if not os.path.exists(src):
        print("missing input:", src)
        return 2
    os.makedirs(outdir, exist_ok=True)
    if not os.path.exists(os.path.join(MODEL_DIR, MODEL_NAME)):
        print("missing model")
        return 2

    from audio_separator.separator import Separator

    sep = Separator(model_file_dir=MODEL_DIR, output_dir=outdir,
                    output_format="WAV", use_autocast=False)
    sep.load_model(model_filename=MODEL_NAME)
    files = sep.separate(src)

    picked = None
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(outdir, os.path.basename(f))
        print("OUT", p, flush=True)
        name = os.path.basename(p).lower()
        if "no reverb" in name or "no_reverb" in name:
            picked = p
    if not picked:
        for f in files:
            p = f if os.path.isabs(f) else os.path.join(outdir, os.path.basename(f))
            if "reverb" not in os.path.basename(p).lower():
                picked = p
                break
    print("PICK", picked or "", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
