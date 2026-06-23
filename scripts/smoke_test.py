"""Headless self-check: imports, InsightFace, DB self-match, mock generation. No camera."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from heyou import db
from heyou.config import load_config
from heyou.generation.mock import MockBackend
from heyou.recognition import FaceRecognizer, best_match


def main() -> int:
    cfg = load_config()
    cfg.ensure_dirs()
    print("1) imports + config OK")

    rec = FaceRecognizer(
        cfg.recognition.model_pack, cfg.recognition.providers,
        cfg.recognition.ctx_id, cfg.recognition.det_size,
    )
    print("2) InsightFace model loaded")

    from insightface.data import get_image as ins_get_image
    img = ins_get_image("t1")  # sample image bundled with insightface
    faces = rec.detect(img)
    print(f"3) detected {len(faces)} face(s) on sample image")
    assert faces, "no faces detected on sample image"
    emb = np.asarray(faces[0].normed_embedding, dtype=np.float32)

    sample_path = cfg.enrolled_dir / "_smoke_sample.jpg"
    cv2.imwrite(str(sample_path), img)

    test_db = cfg.data_path / "_smoke.db"
    test_db.unlink(missing_ok=True)
    db.init_db(test_db)
    pid = db.add_person(test_db, "Sample", emb, str(sample_path))
    person, sim = best_match(emb, db.get_gallery(test_db), cfg.recognition.match_threshold)
    print(f"4) DB + self-match: {person['name'] if person else None} sim={sim:.3f}")
    assert person and person["id"] == pid and sim > 0.99

    out = MockBackend(cfg).generate(str(sample_path), seed=42, style_params={})
    out_path = cfg.output_dir / "_smoke_mock.png"
    out_path.write_bytes(out)
    print(f"5) mock backend generated {len(out)} bytes → {out_path}")

    test_db.unlink(missing_ok=True)
    print("\nALL CHECKS PASSED ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
