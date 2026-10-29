import json, sys
from pathlib import Path
sys.path.insert(0, "/mnt/project-files/tools")
from PIL import Image
import csj_run, csj_build, csj_gates, csj_banner_fit, csj_asset_upload

OUT = Path("/mnt/project-files/tests/heavygod/build_notfinal")
ROWS = "/mnt/project-files/tests/heavygod/rows_final"
clip = "heavygod_test"
inputs = json.loads(Path("/mnt/project-files/tests/heavygod/inputs.json").read_text())
inputs["source"] = "/mnt/project-files/tests/heavygod/heavygod_source.mp4"
assets = csj_run.pick_player_assets(inputs)
inputs = dict(inputs, banner=assets["banner"], figure=assets["character"])
with Image.open(inputs["banner"]) as b:
    if b.size != (csj_banner_fit.BOX_W, csj_banner_fit.BOX_H):
        fitted = OUT / f"{clip}_banner_fitted.png"
        csj_banner_fit.fit(inputs["banner"], str(fitted))
        inputs = dict(inputs, banner=str(fitted))
onsets = json.loads((OUT / f"{clip}_onsets.json").read_text())
timings = csj_build.build(inputs, onsets, ROWS, OUT)
print("build:", timings["build"])
gates = csj_gates.run(timings["build"], inputs, onsets, timings, ROWS,
                      OUT / f"{clip}_layout.json", OUT / f"{clip}_gates.json")
print("gates blocking_pass:", gates["blocking_pass"], "stopped_at:", gates.get("stopped_at"))
print(json.dumps(gates, indent=1)[:4000])
up = csj_asset_upload.upload_clip(timings["build"], clip)
print("upload:", json.dumps(up, indent=1))
