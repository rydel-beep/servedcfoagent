"""READ-ONLY: which tracker rows carry the businesses the unmatched charges'
domains/descriptions point at (#170 ruling 3 proposals)."""
import json, re
import attribution_engine as AE
TOK = {"rising sun": "Adrian Sheather", "hanmade": "Hannah Tamayo", "whistler": "John Elsley",
       "peter": "Clement Peter", "fusion": "Clement Peter", "an di": "Thi Kim Chi Bui",
       "andi": "Thi Kim Chi Bui", "took": "Thuong Tran", "angkor": "Ronny Herrmann",
       "isht": "kranthi pasham", "musty": "Manpreet Sekhon", "butler": "Jagjeet Singh",
       "yo momma": "M Shahinur Hasan", "triton": "Xuan Hieo Nguyen", "gone burger": "Jeni Arul Pragasam",
       "acabo": "norvin Acabo", "sheather": "Adrian Sheather", "prashant": "Prashant Sharma",
       "mahinay": "Dexter Mahinay", "momwong": "Siwakorn Momwong", "anna webb": "Anna Webb",
       "nirav": "Nirav Patel", "khanh": "Khanh Phan", "geertsma": "Ami Geertsma",
       "sekhon": "Manpreet Sekhon", "elsley": "John Elsley", "pasham": "kranthi pasham",
       "herrmann": "Ronny Herrmann", "nguyen": "Xuan Hieo Nguyen", "arul": "Jeni Arul Pragasam",
       "hasan": "M Shahinur Hasan", "tran": "Thuong Tran"}
leads, _ = AE.parse_tracker(AE._tracker_rows_clean())
for tok, payer in TOK.items():
    hits = [l for l in leads if re.search(r"\b" + re.escape(tok), (str(l.get("business") or "") + " " + str(l.get("name") or "")).lower())]
    for l in hits[:3]:
        print(json.dumps({"payer": payer, "token": tok, "name": l.get("name"), "business": l.get("business"),
                          "won": l.get("won"), "offer": l.get("offer"), "close_date": str(l.get("close_date")),
                          "contract": l.get("contract")}, default=str))
