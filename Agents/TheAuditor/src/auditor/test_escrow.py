"""Manual probe for the AGORA escrow invariant (I-X3) — run INSIDE the auditor container.

The auditor's read-only asyncpg pools (and the FRAME_*_REG_DSN / FRAME_*_TEG_DSN that
feed them) only exist in the running container, so this is meant to be executed there:

    docker exec agentvault-the-auditor python -m auditor.test_escrow
    # (use the actual auditor container name: `docker ps | grep -i auditor`)

It builds the frame configs EXACTLY as main.py does (it imports config.FRAMES) and runs
`_escrow_invariant` against the prod frames (frame-c first — the BVT venue — then frame-a),
printing actual / expected / delta / funding / status. READ-ONLY; touches no DB writeably.
"""
import asyncio

from .config import FRAMES
from .main import _escrow_invariant, _reg_pools, _teg_pools, _pools

# Probe the prod venue frames. frame-c (BVT) is the smallest/cleanest venue; frame-a
# (AVT genesis) is the busiest. Override by passing frame ids on argv.
DEFAULT_TARGETS = ["frame-c", "frame-a", "frame-b"]


async def _run(target_ids: list[str]) -> None:
    by_id = {f["id"]: f for f in FRAMES}
    print(f"Configured frames: {sorted(by_id)}")
    for fid in target_ids:
        frame = by_id.get(fid)
        print("\n" + "=" * 72)
        if frame is None:
            print(f"[{fid}] NOT CONFIGURED (no URL/DSN env) — skipped")
            continue
        print(f"[{fid}] {frame['name']} ({frame.get('currency')}) "
              f"reg_dsn={'set' if frame.get('reg_dsn') else 'MISSING'} "
              f"teg_dsn={'set' if frame.get('teg_dsn') else 'MISSING'}")
        try:
            res = await _escrow_invariant(frame)
        except Exception as e:  # _escrow_invariant should never raise; belt + suspenders
            print(f"[{fid}] UNEXPECTED EXCEPTION: {type(e).__name__}: {e}")
            continue
        if res is None:
            print(f"[{fid}] result=None (frame not equipped: no registry/TEG DSN) — I-X3 omitted")
            continue
        if res.get("status") == "ERROR":
            print(f"[{fid}] status=ERROR — {res.get('error')}")
            continue
        print(f"[{fid}] status   = {res['status']}  (confirmed={res['confirmed']})")
        print(f"[{fid}] actual   = {res['actual']}   (TEG escrow agent liquid balance)")
        print(f"[{fid}] expected = {res['expected']}   (registry 5-term escrow sum)")
        print(f"[{fid}] delta    = {res['delta']}   (actual − expected)")
        print(f"[{fid}] funding  = n={res['funding_n']} notional={res['funding_notional']} "
              f"(legitimate in-flight window)")
        print(f"[{fid}] verdict  = {'OK — within funding window / tolerance' if res['status'] == 'OK' else 'BREACH — persisted & beyond funding window'}")

    # Tidy up the read-only pools we opened.
    for pool_map in (_reg_pools, _teg_pools, _pools):
        for pool in list(pool_map.values()):
            try:
                await pool.close()
            except Exception:
                pass


def main() -> None:
    import sys
    targets = sys.argv[1:] or DEFAULT_TARGETS
    asyncio.run(_run(targets))


if __name__ == "__main__":
    main()
