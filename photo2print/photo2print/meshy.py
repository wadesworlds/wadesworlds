"""Step 3a: Meshy Image-to-3D API client (needs MESHY_API_KEY)."""
import base64
import mimetypes
import os
import time

import requests

API = "https://api.meshy.ai/openapi/v1/image-to-3d"


def _image_ref(image):
    if image.startswith(("http://", "https://", "data:")):
        return image
    mime = mimetypes.guess_type(image)[0] or "image/png"
    with open(image, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def image_to_3d(image, out_path, ai_model="latest", target_polycount=300000,
                api_key=None, poll_seconds=10, timeout_minutes=30, extra=None):
    """Submit an image, wait for the textured model, download the GLB."""
    key = api_key or os.environ.get("MESHY_API_KEY")
    if not key:
        raise SystemExit("Set MESHY_API_KEY (Meshy dashboard -> API) or pass --api-key")
    headers = {"Authorization": f"Bearer {key}"}
    body = {
        "image_url": _image_ref(image),
        "ai_model": ai_model,
        "should_texture": True,
        "enable_pbr": False,
        "topology": "triangle",
        "target_polycount": target_polycount,
    }
    body.update(extra or {})
    r = requests.post(API, json=body, headers=headers, timeout=120)
    if not r.ok:
        raise SystemExit(f"Meshy rejected the request ({r.status_code}): {r.text}")
    task_id = r.json()["result"]
    print(f"Meshy task {task_id} submitted (ai_model={ai_model})")

    deadline = time.time() + timeout_minutes * 60
    while True:
        t = requests.get(f"{API}/{task_id}", headers=headers, timeout=60).json()
        status = t.get("status")
        print(f"  {status} {t.get('progress', 0)}%")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "CANCELED", "EXPIRED"):
            raise SystemExit(f"Meshy task {status}: {t.get('task_error')}")
        if time.time() > deadline:
            raise SystemExit(f"Timed out waiting for Meshy task {task_id}")
        time.sleep(poll_seconds)

    url = t["model_urls"]["glb"]
    with requests.get(url, stream=True, timeout=300) as dl:
        dl.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in dl.iter_content(1 << 20):
                f.write(chunk)
    print(f"Saved {out_path}")
    return out_path
