"""
scripts/seed_ra2_mapping.py — one-time R-A2 set-mapping seed (journaled,
reversible in the strategy panel).

Maps ONLY the two ad sets whose Meta names unambiguously declare the new
strategy's roles (created for R-A2, 4 video ads each):
  120249957643900167 "Served Video AI Broad Ad Set"       → broad_video
  120249957709950167 "Served Video Interests Targ Ad Set" → targeted_video
Graphics + Retargeting are left UNMAPPED for Rydel (no Meta set with those
names has delivery yet) — they surface honestly in the panel.
"""
import json

import ads_lifecycle as L

SEED = {"120249957643900167": "broad_video",
        "120249957709950167": "targeted_video"}


def main():
    out = {}
    actor = {"user": "migration-seed (verify in panel)"}
    for sid, role in SEED.items():
        cur = L.set_roles_map().get(sid)
        if cur == role:
            out[sid] = f"already {role}"
            continue
        res, err = L.map_adset(actor, sid, role)
        out[sid] = err or f"mapped → {role}"
    out["mapping_now"] = L.set_roles_map()
    out["journal_tail"] = L.strategy_journal()[-4:]
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
