"""V0653 (ao) item 3 (the dev machine's beta.30 test, room seq 582 and 587/588): the kit names images by their public names,
says which ones it will use, and reports the runner's adoption as a sentence.

- the standup driver logged `image: agentvault2-registry-test:latest -> <image>`: the template's internal build name, on
  a stranger's screen. It logs the service's role and the image it runs now (image_rewrites).
- frame-doctor says which prefix and images frame-up will use, why that prefix, and which are on the host already, in
  its text and in --json (image_plan).
- frame-up printed the runner's adopt answer as JSON cut at 120 characters; it says what happened now (adopt_sentence).
BASE (kit beta.31): none of these functions exists, and the driver's line names the internal image.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fu = _load("frame_up_v0653", os.path.join(HERE, "..", "frame-up.py"))
fd = _load("frame_doctor_v0653", os.path.join(HERE, "..", "frame-doctor.py"))
drv = _load("standup_driver_v0653", os.path.join(HERE, "..", "..", "hetzner_demo", "standup_driver.py"))


def test_the_driver_names_the_role_and_the_image_never_the_template_name():
    comp = "services:\n  r:\n    image: agentvault2-registry-test:latest\n  t:\n    image: agentvault2-teg-layer-test:latest\n"
    out, lines = drv.image_rewrites(comp, {"agentvault2-registry-test:latest": "images.theprotocol.cloud/theprotocol/registry:V0653",
                                            "agentvault2-teg-layer-test:latest": "images.theprotocol.cloud/theprotocol/teg-layer:V0653",
                                            "agentvault2-event-store-test:latest": "unused"})
    assert "agentvault2-" not in out and "agentvault2-" not in " ".join(lines)
    assert lines == ["image: registry runs images.theprotocol.cloud/theprotocol/registry:V0653",
                     "image: teg-layer runs images.theprotocol.cloud/theprotocol/teg-layer:V0653"]


def test_the_doctor_says_which_prefix_and_why(monkeypatch):
    monkeypatch.delenv("IMAGE_REGISTRY", raising=False)
    assert fd.images_prefix_choice("V0653", inspect=lambda ref: False) == (
        fd.PUBLIC_IMAGES_PREFIX, "the release channel's public namespace (build.sh's six are not all here)")
    assert fd.images_prefix_choice("V0653", inspect=lambda ref: True)[0] == fd.LOCAL_IMAGES_PREFIX
    monkeypatch.setenv("IMAGE_REGISTRY", "registry.example/tp")
    assert fd.images_prefix_choice("V0653", inspect=lambda ref: False) == ("registry.example/tp", "IMAGE_REGISTRY names it")
    assert fd.default_images_prefix("V0653", inspect=lambda ref: False) == "registry.example/tp"


def test_the_doctor_names_the_images_present_and_to_pull_in_text_and_json():
    have = {f"{fd.PUBLIC_IMAGES_PREFIX}/registry:V0653", f"{fd.PUBLIC_IMAGES_PREFIX}/teg-layer:V0653"}
    plan = fd.image_plan(fd.PUBLIC_IMAGES_PREFIX, "V0653", "the release channel's public namespace", inspect=have.__contains__)
    assert len(plan["refs"]) == 6 and set(plan["present"]) == have and len(plan["to_pull"]) == 4
    assert all("agentvault2-" not in r for r in plan["refs"])
    json.dumps(plan)                                           # what --json prints under "images"
    assert fd.image_plan_line(plan) == ("images: frame-up will use images.theprotocol.cloud/theprotocol/<name>:V0653 "
                                        "(the release channel's public namespace): 2 of 6 on this host; frame-up pulls 4")


def test_the_adoption_reads_as_a_sentence():
    new = json.dumps({"name": "lantern", "stack_dir": "/s/lantern-1", "recorded": True, "already": False, "adopted": True})
    old = json.dumps({"name": "lantern", "stack_dir": "/s/lantern-1", "recorded": False, "already": True, "adopted": True})
    assert fu.adopt_sentence("lantern", new + "\n", {"socket_gid": 998}) == \
        "frame runner: adopted lantern (a new record); its registry reaches the runner through socket group 998"
    assert fu.adopt_sentence("lantern", old, {"socket_gid": 998}).startswith("frame runner: adopted lantern (it was already recorded)")
    assert fu.adopt_sentence("lantern", "", {}) == "frame runner: adopted lantern (recorded)"
